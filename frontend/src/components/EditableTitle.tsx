import { useEffect, useRef, useState, KeyboardEvent } from "react";

/**
 * Inline-editable text. Click (or double-click, via `trigger`) to edit;
 * Enter/blur commits, Escape cancels. Empty input reverts to the old value.
 */
export function EditableTitle({
  value,
  onCommit,
  className = "",
  inputClassName = "",
  title,
}: {
  value: string;
  onCommit: (next: string) => void;
  className?: string;
  inputClassName?: string;
  title?: string;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editing) {
      inputRef.current?.focus();
      inputRef.current?.select();
    }
  }, [editing]);

  const start = () => {
    setDraft(value);
    setEditing(true);
  };

  const commit = () => {
    const next = draft.trim();
    setEditing(false);
    if (next && next !== value) onCommit(next);
  };

  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      commit();
    } else if (e.key === "Escape") {
      e.preventDefault();
      setEditing(false);
    }
  };

  if (editing) {
    return (
      <input
        ref={inputRef}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={onKey}
        onBlur={commit}
        onClick={(e) => e.stopPropagation()}
        className={`rounded-md border border-azure bg-void px-1.5 py-0.5 text-primary outline-none ${inputClassName}`}
      />
    );
  }

  return (
    <span
      className={`cursor-text rounded px-0.5 hover:bg-raised/60 ${className}`}
      title={title ?? "Click to rename"}
      onClick={(e) => {
        e.stopPropagation();
        start();
      }}
    >
      {value}
    </span>
  );
}
