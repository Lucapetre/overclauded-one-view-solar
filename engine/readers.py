"""Format readers selected by profile configuration (never by vendor name).

* ``ndjson_envelope``: one JSON object per line (optionally gzip-compressed): a collector/transport envelope plus
  the native payload. Lines are handed to the shared Ingestor unchanged.
* ``header_csv``: a bounded text table with N header rows (environment line, field names, units, processing
  descriptors; positions configured) followed by comma-separated records, e.g. a datalogger table export. Each data
  row becomes one delivery: {collector envelope from the file's sidecar metadata, payload {header, row, row_text}}.
  Unquoted numeric tokens are numbers; quoted tokens stay strings (configured missing tokens such as "NAN" are
  resolved later by the profile's numeric.missing_tokens, never replaced by another sensor).

Component manifests may reference files outside the input root ONLY under an explicitly declared external root
(e.g. the existing provider fixture directory) and only with a pinned sha256. Evaluation-only material is refused.
"""
from __future__ import annotations

import gzip
import io
import json
from pathlib import Path

from .transport import EvaluationMaterialError, guard, sha256_file

EVALUATION_NAMES = {"component_truth", "fault_manifest.json"}
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_LINE_BYTES = 1024 * 1024


class ReaderError(ValueError):
    pass


def eval_guard(path: Path) -> Path:
    p = guard(path)
    if {x.lower() for x in p.parts} & EVALUATION_NAMES:
        raise EvaluationMaterialError(f"refusing to read evaluation-only material: {p}")
    return p


def _inside(p: Path, root: Path) -> bool:
    try:
        p.relative_to(root)
        return True
    except ValueError:
        return False


def discover_components(input_root: Path, datasets, families=None):
    """Yield (abs_path, rel_label, entry) for manifest-listed files of the wanted datasets/families."""
    root = eval_guard(Path(input_root))
    man = root / "manifest.json"
    if not man.exists():
        raise ReaderError(f"{man} not found")
    doc = json.loads(man.read_text(encoding="utf-8"))
    ext_roots = {k: eval_guard((root / v).resolve()) for k, v in (doc.get("external_roots") or {}).items()}
    for f in doc.get("files", []):
        if f.get("dataset") not in datasets:
            continue
        if families is not None and f.get("family") not in families:
            continue
        p = eval_guard((root / f["path"]).resolve())
        if _inside(p, root):
            rel = p.relative_to(root).as_posix()
        else:
            hit = [k for k, r in ext_roots.items() if _inside(p, r)]
            if not hit:
                raise ReaderError(f"{f['path']} is outside the input root and outside every declared external root")
            if not f.get("sha256"):
                raise ReaderError(f"external reference {f['path']} must carry a pinned sha256")
            rel = f"{hit[0]}:{p.relative_to(ext_roots[hit[0]]).as_posix()}"
        if p.stat().st_size > MAX_FILE_BYTES:
            raise ReaderError(f"{rel} exceeds the {MAX_FILE_BYTES} byte input bound")
        yield p, rel, f


def checksum_ok(path: Path, entry) -> tuple[bool, str]:
    actual = sha256_file(path)
    return (entry.get("sha256") in (None, actual)), actual


def _open_text(path: Path):
    if path.suffix == ".gz":
        return io.TextIOWrapper(gzip.open(path, "rb"), encoding="utf-8", newline="")
    return open(path, "r", encoding="utf-8", newline="")


def ndjson_lines(path: Path):
    """Yield (line_no, line) of an NDJSON file (plain or .gz); blank lines skipped; oversized lines rejected."""
    with _open_text(path) as fh:
        for n, line in enumerate(fh, 1):
            line = line.rstrip("\n").rstrip("\r")
            if not line.strip():
                continue
            if len(line) > MAX_LINE_BYTES:
                raise ReaderError(f"{path.name}:{n} exceeds the {MAX_LINE_BYTES} byte line bound")
            yield n, line


def binding_filter_ok(line: str, flt) -> bool:
    """Optional manifest filter on the envelope binding (used to take ONE site's lines from a shared file)."""
    if not flt:
        return True
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return False
    for key in ("mock_transport", "collector"):
        env = obj.get(key) if isinstance(obj, dict) else None
        if isinstance(env, dict):
            b = env.get("binding") or {}
            return all(str(b.get(k)) in [str(x) for x in v] for k, v in flt.items())
    return False


def _token(raw: str, quoted: bool):
    if quoted:
        return raw
    s = raw.strip()
    try:
        if s.lstrip("+-").isdigit():
            return int(s)
        return float(s) if s.lower() not in ("nan", "inf", "-inf", "infinity") else s
    except ValueError:
        return s


def _split_row(line: str, delim=","):
    """CSV split that remembers which tokens were quoted (csv module drops that information)."""
    out, i, n = [], 0, len(line)
    while i <= n:
        if i < n and line[i] == '"':
            j, buf = i + 1, []
            while j < n:
                if line[j] == '"':
                    if j + 1 < n and line[j + 1] == '"':
                        buf.append('"')
                        j += 2
                        continue
                    break
                buf.append(line[j])
                j += 1
            if j >= n:
                raise ReaderError("unterminated quoted field")
            out.append(("".join(buf), True))
            i = j + 1
            if i < n and line[i] != delim:
                raise ReaderError("characters after a closing quote")
            i += 1
        else:
            j = line.find(delim, i)
            j = n if j < 0 else j
            out.append((line[i:j], False))
            i = j + 1
            if j == n:
                break
    return out


def header_csv_deliveries(path: Path, cfg: dict, envelope_key: str = "collector"):
    """Yield (line_no, delivery_line) for each data row of a header_csv file (e.g. a datalogger table)."""
    hr = int(cfg["header_rows"])
    rows_max = int(cfg.get("max_rows", 200000))
    cols_max = int(cfg.get("max_columns", 64))
    line_max = int(cfg.get("max_line_bytes", 4096))
    side = path.with_name(path.name + cfg.get("sidecar_suffix", ".collector.json"))
    if not side.exists():
        raise ReaderError(f"{path.name}: collector sidecar {side.name} missing (source identity/capture metadata)")
    env = json.loads(eval_guard(side).read_text(encoding="utf-8"))
    header, n_rows = [], 0
    with _open_text(path) as fh:
        for n, line in enumerate(fh, 1):
            line = line.rstrip("\n").rstrip("\r")
            if len(line) > line_max:
                raise ReaderError(f"{path.name}:{n} exceeds {line_max} bytes")
            if n <= hr:
                header.append([t for t, _ in _split_row(line)])
                if n == hr:
                    names = header[int(cfg["names_row"]) - 1]
                    if len(names) > cols_max or len(set(names)) != len(names):
                        raise ReaderError(f"{path.name}: column names missing, duplicated or above {cols_max}")
                    env_row = header[int(cfg.get("environment_row", 1)) - 1]
                    want = cfg.get("expect_environment_first")
                    if want and (not env_row or env_row[0] != want):
                        raise ReaderError(f"{path.name}: first header token {env_row[:1]} != {want!r}")
                    hdr = {"environment": env_row, "fields": names}
                    for k in ("units_row", "processing_row"):
                        if cfg.get(k):
                            vals = header[int(cfg[k]) - 1]
                            hdr[k.replace("_row", "")] = dict(zip(names, vals))
                continue
            if not line.strip():
                continue
            n_rows += 1
            if n_rows > rows_max:
                raise ReaderError(f"{path.name}: more than {rows_max} data rows")
            toks = _split_row(line)
            if len(toks) != len(names):
                row = {"__malformed__": line}
            else:
                row = {k: _token(v, q) for k, (v, q) in zip(names, toks)}
            e = {k: v for k, v in env.items() if k != "collections"}
            col = next((c for c in env.get("collections") or [] if c["through_line"] >= n), None)
            if col is None:
                raise ReaderError(f"{path.name}:{n} is not covered by any collection event in the sidecar")
            e.update(recorded_at_utc=col["recorded_at_utc"], received_at_utc=col["received_at_utc"],
                     delivery_id=f"{env.get('delivery_id_prefix', path.stem)}-L{n:06d}", source_file_line=n)
            yield n, json.dumps({envelope_key: e, "payload": {"header": hdr, "row": row, "row_text": line}},
                                separators=(",", ":"), ensure_ascii=False, sort_keys=False)
