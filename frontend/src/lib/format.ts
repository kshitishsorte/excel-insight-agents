/** Human-friendly duration: 47 -> "47s", 392 -> "6m 32s". */
export function fmtDuration(secs: number | null | undefined): string {
  if (secs == null || isNaN(secs)) return "";
  const s = Math.max(0, Math.round(secs));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  return `${m}m ${String(s % 60).padStart(2, "0")}s`;
}

/** Stopwatch-style elapsed for status timestamps: 3 -> "0:03", 105 -> "1:45". */
export function fmtElapsed(secs: number | null | undefined): string {
  if (secs == null || isNaN(secs)) return "";
  const s = Math.max(0, Math.round(secs));
  const m = Math.floor(s / 60);
  return `${m}:${String(s % 60).padStart(2, "0")}`;
}
