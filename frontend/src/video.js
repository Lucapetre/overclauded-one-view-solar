// Support video rules shared by the request form and "Attach a video". Pure.
// The server re-checks type, size and file signature; duration is checked only here.
export const VIDEO_TYPES = { "video/mp4": ".mp4", "video/webm": ".webm" };
export const MAX_VIDEO_BYTES = 30 * 1024 * 1024;
export const MAX_VIDEO_SECONDS = 60;

/** The accepted MIME type of a file-like { name, type }, or null. */
export function videoType(file) {
  const type = String(file?.type || "").toLowerCase();
  if (type in VIDEO_TYPES) return type;
  if (type) return null;
  const name = String(file?.name || "").toLowerCase();
  if (name.endsWith(".mp4")) return "video/mp4";
  if (name.endsWith(".webm")) return "video/webm";
  return null;
}

/** "830 bytes", "12.4 KB", "4.2 MB". */
export function humanSize(bytes) {
  if (!Number.isFinite(bytes) || bytes < 0) return "unknown size";
  if (bytes < 1024) return `${bytes} bytes`;
  const fmt = (n) =>
    new Intl.NumberFormat("en-GB", { maximumFractionDigits: 1 }).format(n);
  if (bytes < 1024 * 1024) return `${fmt(bytes / 1024)} KB`;
  return `${fmt(bytes / (1024 * 1024))} MB`;
}

/** A plain sentence when the file cannot be sent, otherwise null. */
export function videoProblem(file) {
  if (!file) return null;
  if (!videoType(file)) return "Use an MP4 or WebM video.";
  if (!file.size) return "This video file is empty.";
  if (file.size > MAX_VIDEO_BYTES)
    return `This video is ${humanSize(file.size)}; the limit is 30 MB.`;
  return null;
}

/** A plain sentence when the measured duration is not acceptable, otherwise null. */
export function durationProblem(seconds) {
  if (!Number.isFinite(seconds) || seconds <= 0)
    return "We could not read how long this video is. Try another MP4 or WebM file.";
  if (seconds > MAX_VIDEO_SECONDS + 0.5)
    return `This video is ${Math.round(seconds)} seconds long; keep it to ${MAX_VIDEO_SECONDS} seconds or less.`;
  return null;
}
