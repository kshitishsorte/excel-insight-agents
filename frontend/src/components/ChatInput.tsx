import { useState, KeyboardEvent } from "react";
import { ArrowUp } from "lucide-react";

export function ChatInput({
  onSend,
  disabled,
  placeholder,
}: {
  onSend: (text: string) => void;
  disabled?: boolean;
  placeholder?: string;
}) {
  const [text, setText] = useState("");

  const submit = () => {
    const t = text.trim();
    if (!t || disabled) return;
    onSend(t);
    setText("");
  };

  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <div className="border-t border-hairline px-4 py-3">
      <div className="mx-auto flex max-w-[760px] items-end gap-2">
        <div className="flex flex-1 items-end rounded-2xl border border-hairline bg-surface px-3 py-2 focus-within:border-azure">
          <textarea
            rows={1}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={onKey}
            disabled={disabled}
            placeholder={placeholder ?? "Ask a question…"}
            className="max-h-40 min-h-[24px] flex-1 resize-none bg-transparent text-[14px] text-primary placeholder:text-muted focus:outline-none disabled:opacity-50"
          />
        </div>
        <button
          onClick={submit}
          disabled={disabled || !text.trim()}
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl text-white transition-opacity disabled:opacity-40"
          style={{ background: "var(--signature)" }}
          aria-label="Send message"
        >
          <ArrowUp size={18} />
        </button>
      </div>
    </div>
  );
}
