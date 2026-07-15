import { useEffect, useRef, useState } from "react";
import { Plus, FileSpreadsheet, Trash2, Circle, Pencil } from "lucide-react";
import type { ProjectStatus, ProjectSummary } from "../types";

const STATUS_DOT: Record<ProjectStatus, string> = {
  empty: "text-muted",
  queued: "text-violet",
  running: "text-aqua",
  ready: "text-azure",
  error: "text-red-400",
};

export function Sidebar({
  projects,
  activeId,
  onSelect,
  onNew,
  onDelete,
  onRename,
  health,
}: {
  projects: ProjectSummary[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
  onRename: (id: string, name: string) => void;
  health: { ollama_ok: boolean; detail: string } | null;
}) {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editingId) {
      inputRef.current?.focus();
      inputRef.current?.select();
    }
  }, [editingId]);

  const startEdit = (p: ProjectSummary) => {
    setDraft(p.name);
    setEditingId(p.id);
  };
  const commit = (id: string) => {
    const next = draft.trim();
    setEditingId(null);
    if (next) onRename(id, next);
  };

  return (
    <div className="flex h-full w-[260px] flex-col border-r border-hairline bg-surface">
      <div className="px-4 pb-3 pt-4">
        <div className="mb-4 flex items-center gap-2">
          <div className="h-6 w-6 rounded-md" style={{ background: "var(--signature)" }} />
          <span className="font-display text-[15px] font-600 tracking-tight">Insight Agents</span>
        </div>
        <button
          onClick={onNew}
          className="flex w-full items-center justify-center gap-2 rounded-lg border border-hairline bg-raised px-3 py-2 text-sm font-500 text-primary transition-colors hover:border-azure"
        >
          <Plus size={16} /> New project
        </button>
      </div>

      <nav className="flex-1 overflow-y-auto px-2 py-1">
        {projects.length === 0 && (
          <p className="px-2 py-4 text-center text-xs text-muted">No projects yet.</p>
        )}
        {projects.map((p) => {
          const active = p.id === activeId;
          const isEditing = editingId === p.id;
          return (
            <div
              key={p.id}
              className={`group mb-0.5 flex cursor-pointer items-center gap-2 rounded-lg px-2.5 py-2 text-sm transition-colors ${
                active ? "bg-raised text-primary" : "text-muted hover:bg-raised/60 hover:text-primary"
              }`}
              onClick={() => !isEditing && onSelect(p.id)}
              onDoubleClick={() => startEdit(p)}
            >
              {p.has_report ? (
                <FileSpreadsheet size={15} className="shrink-0 text-azure" />
              ) : (
                <Circle size={9} className={`ml-[3px] shrink-0 ${STATUS_DOT[p.status]}`} fill="currentColor" />
              )}

              {isEditing ? (
                <input
                  ref={inputRef}
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  onClick={(e) => e.stopPropagation()}
                  onBlur={() => commit(p.id)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") commit(p.id);
                    else if (e.key === "Escape") setEditingId(null);
                  }}
                  className="min-w-0 flex-1 rounded-md border border-azure bg-void px-1.5 py-0.5 text-sm text-primary outline-none"
                />
              ) : (
                <span className="min-w-0 flex-1 truncate">{p.name}</span>
              )}

              {!isEditing && (
                <>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      startEdit(p);
                    }}
                    className="shrink-0 rounded p-1 text-muted opacity-0 transition-opacity hover:text-azure group-hover:opacity-100"
                    aria-label="Rename project"
                  >
                    <Pencil size={13} />
                  </button>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      if (confirm(`Delete "${p.name}"?`)) onDelete(p.id);
                    }}
                    className="shrink-0 rounded p-1 text-muted opacity-0 transition-opacity hover:text-red-400 group-hover:opacity-100"
                    aria-label="Delete project"
                  >
                    <Trash2 size={13} />
                  </button>
                </>
              )}
            </div>
          );
        })}
      </nav>

      <div className="border-t border-hairline px-4 py-3">
        <div className="flex items-center gap-2 text-xs text-muted">
          <span
            className={`h-2 w-2 rounded-full ${health?.ollama_ok ? "bg-aqua" : "bg-red-400"}`}
            title={health?.detail}
          />
          <span className="font-mono">{health?.ollama_ok ? "Ollama connected" : "Ollama offline"}</span>
        </div>
      </div>
    </div>
  );
}
