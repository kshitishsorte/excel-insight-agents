import { useEffect, useRef } from "react";
import type { Message } from "../types";
import { MessageBubble } from "./MessageBubble";
import { AgentStatusLine } from "./AgentStatusLine";
import { fmtElapsed } from "../lib/format";

interface LiveStatus {
  detail: string;
  round?: number;
  max_rounds?: number;
}

export function ChatThread({
  messages,
  liveAssistant,
  liveStatus,
  chatStatus,
}: {
  messages: Message[];
  liveAssistant: string | null;
  liveStatus: LiveStatus | null;
  chatStatus?: string | null;
}) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length, liveAssistant, liveStatus?.detail, chatStatus]);

  // The current stage arrives as BOTH a stored status message and a live event —
  // only show the live spinner line when it isn't already the last stored line.
  const lastStatus = [...messages].reverse().find((m) => m.kind === "status");
  const showLive = liveStatus && (!lastStatus || lastStatus.content !== liveStatus.detail);

  // Stopwatch elapsed per status line, measured from the first status line of the
  // same run (a contiguous block of status messages). The gap between lines shows
  // how long each step took; the last line ≈ total pipeline time.
  const elapsed: Record<string, string> = {};
  let runStart: number | null = null;
  for (let i = 0; i < messages.length; i++) {
    const m = messages[i];
    if (m.kind === "status") {
      if (runStart === null || messages[i - 1]?.kind !== "status") runStart = m.ts;
      elapsed[m.id] = fmtElapsed(m.ts - runStart);
    } else {
      runStart = null;
    }
  }

  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto flex max-w-[760px] flex-col gap-3 px-4 py-6">
        {messages.map((m) =>
          m.kind === "status" ? (
            <AgentStatusLine key={m.id} text={m.content} time={elapsed[m.id]} />
          ) : (
            <MessageBubble key={m.id} message={m} />
          )
        )}

        {showLive && <AgentStatusLine text={liveStatus!.detail} live />}

        {/* Chat working indicator (routing / running analysis / summarising) */}
        {chatStatus && liveAssistant === null && <AgentStatusLine text={chatStatus} live />}

        {liveAssistant !== null && (
          <MessageBubble
            message={{ id: "live", role: "assistant", kind: "chat", content: liveAssistant, ts: 0 }}
            streaming
          />
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
