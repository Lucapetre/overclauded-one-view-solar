import test from "node:test";
import assert from "node:assert/strict";
import {
  MAX_VIDEO_BYTES,
  durationProblem,
  humanSize,
  videoProblem,
  videoType,
} from "../src/video.js";

test("only MP4 and WebM are accepted; the extension helps when the type is empty", () => {
  assert.equal(videoType({ name: "a.mp4", type: "video/mp4" }), "video/mp4");
  assert.equal(videoType({ name: "a.webm", type: "VIDEO/WEBM" }), "video/webm");
  assert.equal(videoType({ name: "clip.MP4", type: "" }), "video/mp4");
  assert.equal(videoType({ name: "clip.mov", type: "video/quicktime" }), null);
  // A declared non-video type is not overridden by a misleading extension.
  assert.equal(videoType({ name: "notes.mp4", type: "text/plain" }), null);
  assert.equal(videoType({ name: "clip", type: "" }), null);
});

test("size limit is 30 MB; empty files are refused", () => {
  assert.equal(videoProblem(null), null);
  assert.equal(videoProblem({ name: "a.mp4", type: "video/mp4", size: 1000 }), null);
  assert.equal(
    videoProblem({ name: "a.mp4", type: "video/mp4", size: MAX_VIDEO_BYTES }),
    null,
  );
  assert.match(
    videoProblem({ name: "a.mp4", type: "video/mp4", size: MAX_VIDEO_BYTES + 1 }),
    /limit is 30 MB/,
  );
  assert.match(videoProblem({ name: "a.mp4", type: "video/mp4", size: 0 }), /empty/);
  assert.match(
    videoProblem({ name: "a.mov", type: "video/quicktime", size: 10 }),
    /MP4 or WebM/,
  );
});

test("duration must be known and at most 60 seconds", () => {
  assert.equal(durationProblem(12.4), null);
  assert.equal(durationProblem(60), null);
  assert.equal(durationProblem(60.4), null);
  assert.match(durationProblem(61), /61 seconds long/);
  assert.match(durationProblem(Infinity), /could not read/);
  assert.match(durationProblem(NaN), /could not read/);
  assert.match(durationProblem(0), /could not read/);
});

test("human-readable sizes", () => {
  assert.equal(humanSize(830), "830 bytes");
  assert.equal(humanSize(12.4 * 1024), "12.4 KB");
  assert.equal(humanSize(4.2 * 1024 * 1024), "4.2 MB");
  assert.equal(humanSize(MAX_VIDEO_BYTES), "30 MB");
  assert.equal(humanSize(-1), "unknown size");
});
