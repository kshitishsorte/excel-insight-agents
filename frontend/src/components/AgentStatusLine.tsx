import { Loader2 } from "lucide-react";

/** Quiet, small agent-status line — deliberately distinct from chat bubbles.
 *  `time` is a stopwatch-style elapsed stamp (e.g. "0:03") shown in place of the
 *  bullet, so the thread reads like a timeline and shows how long each step took. */
export function AgentStatusLine({
  text,
  live = false,
  time,
}: {
  text: string;
  live?: boolean;
  time?: string;
}) {
  return (
    <div className="flex animate-fade-in items-center gap-2 py-1 pl-1 text-[12.5px] text-muted">
      {live ? (
        <Loader2 size={12} className="shrink-0 animate-spin text-aqua motion-reduce:animate-none" />
      ) : time ? (
        <span className="w-9 shrink-0 text-right font-mono text-[11px] tabular-nums text-muted/70">{time}</span>
      ) : (
        <span className="ml-[3px] mr-[3px] h-1.5 w-1.5 shrink-0 rounded-full bg-hairline" />
      )}
      <span className="font-mono leading-snug">{text}</span>
    </div>
  );
}
