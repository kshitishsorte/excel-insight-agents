import { Mic, MicOff, Loader2 } from "lucide-react";
import type { VoiceState } from "../types";
import type { MicPhase } from "../lib/useVoice";

const STATE_LABEL: Record<string, string> = {
  transcribing: "Transcribing…",
  thinking: "Thinking…",
  speaking: "Speaking…",
  capturing: "Listening…",
  listening: "Ready — just talk",
};

export function VoiceControl({
  enabled,
  warming,
  phase,
  serverState,
  level,
  disabled,
  onToggle,
}: {
  enabled: boolean;
  warming: boolean;
  phase: MicPhase;
  serverState: VoiceState;
  level: number;
  disabled?: boolean;
  onToggle: () => void;
}) {
  const active = serverState !== "idle" ? serverState : phase === "capturing" ? "capturing" : "listening";
  const label = warming ? "Loading voice…" : enabled ? STATE_LABEL[active] : "Voice chat";
  const busy = serverState !== "idle";
  // mic meter (0..1) — only meaningful while actually listening
  const meter = enabled && !busy ? Math.min(1, level / 0.12) : 0;

  return (
    <div className="mx-auto mb-2 flex max-w-[760px] items-center gap-3">
      <button
        onClick={onToggle}
        disabled={disabled || warming}
        className={`flex items-center gap-2 rounded-full border px-3.5 py-2 text-[13px] font-500 transition-colors disabled:opacity-50 ${
          enabled
            ? "border-transparent text-white"
            : "border-hairline text-muted hover:border-azure hover:text-primary"
        }`}
        style={enabled ? { background: "var(--signature)" } : undefined}
        aria-pressed={enabled}
      >
        {warming ? (
          <Loader2 size={15} className="animate-spin motion-reduce:animate-none" />
        ) : enabled ? (
          <Mic size={15} />
        ) : (
          <MicOff size={15} />
        )}
        {enabled ? "Voice on" : "Voice"}
      </button>

      {enabled && (
        <div className="flex min-w-0 flex-1 items-center gap-2.5">
          <span
            className={`h-2 w-2 shrink-0 rounded-full ${
              busy ? "bg-violet" : phase === "capturing" ? "bg-aqua" : "bg-azure"
            } ${serverState === "speaking" || phase === "capturing" ? "animate-pulse motion-reduce:animate-none" : ""}`}
          />
          <span className="truncate text-[12.5px] text-muted">{label}</span>
          {/* live mic meter */}
          <div className="ml-auto hidden h-1.5 w-24 overflow-hidden rounded-full bg-hairline sm:block">
            <div
              className="h-full rounded-full bg-aqua transition-[width] duration-75"
              style={{ width: `${meter * 100}%` }}
            />
          </div>
        </div>
      )}
    </div>
  );
}
