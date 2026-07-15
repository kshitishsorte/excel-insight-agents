import { useCallback, useEffect, useRef, useState } from "react";
import { PanelRight, Menu, X } from "lucide-react";
import { api } from "./lib/api";
import { ProjectSocket } from "./lib/websocket";
import type { Message, ProjectFull, ProjectStatus, ProjectSummary, Report, WsEvent } from "./types";
import { Sidebar } from "./components/Sidebar";
import { ChatThread } from "./components/ChatThread";
import { ChatInput } from "./components/ChatInput";
import { AnalysisCanvas } from "./components/AnalysisCanvas";
import { UploadDropzone } from "./components/UploadDropzone";
import { EditableTitle } from "./components/EditableTitle";
import { VoiceControl } from "./components/VoiceControl";
import { useVoice } from "./lib/useVoice";
import type { VoiceState } from "./types";

interface LiveStatus {
  detail: string;
  round?: number;
  max_rounds?: number;
}

export default function App() {
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [report, setReport] = useState<Report | null>(null);
  const [status, setStatus] = useState<ProjectStatus>("empty");
  const [filename, setFilename] = useState<string | null>(null);
  const [liveAssistant, setLiveAssistant] = useState<string | null>(null);
  const [liveStatus, setLiveStatus] = useState<LiveStatus | null>(null);
  const [chatStatus, setChatStatus] = useState<string | null>(null);
  const [health, setHealth] = useState<{ ollama_ok: boolean; detail: string } | null>(null);
  const [navOpen, setNavOpen] = useState(false);
  const [canvasOpen, setCanvasOpen] = useState(false);
  const [voiceEnabled, setVoiceEnabled] = useState(false);
  const [voiceWarming, setVoiceWarming] = useState(false);
  const [voiceState, setVoiceState] = useState<VoiceState>("idle");
  const [voiceAudio, setVoiceAudio] = useState<{ b64: string; id: string } | null>(null);

  const socketRef = useRef<ProjectSocket | null>(null);
  const activeIdRef = useRef<string | null>(null);
  activeIdRef.current = activeId;

  const refreshProjects = useCallback(async () => {
    const list = await api.listProjects();
    setProjects(list);
    return list;
  }, []);

  // Initial load: health + projects; land on a project (create one if none).
  useEffect(() => {
    (async () => {
      try {
        setHealth(await api.health());
      } catch {
        setHealth({ ollama_ok: false, detail: "Backend unreachable." });
      }
      const list = await refreshProjects();
      if (list.length > 0) setActiveId(list[0].id);
      else {
        const p = await api.createProject();
        await refreshProjects();
        setActiveId(p.id);
      }
    })();
  }, [refreshProjects]);

  const handleEvent = useCallback((e: WsEvent) => {
    switch (e.type) {
      case "message":
        setMessages((prev) =>
          prev.some((m) => m.id === e.message.id) ? prev : [...prev, e.message]
        );
        if (e.message.role === "assistant" && e.message.kind === "chat") {
          setLiveAssistant(null);
          setChatStatus(null);
        }
        break;
      case "chat_status":
        setChatStatus(e.detail);
        break;
      case "status":
        setLiveStatus({ detail: e.detail, round: e.round, max_rounds: e.max_rounds });
        break;
      case "status_change":
        setStatus(e.status);
        setProjects((prev) => prev.map((p) => (p.id === activeIdRef.current ? { ...p, status: e.status } : p)));
        break;
      case "report_ready":
        setReport(e.report);
        setLiveStatus(null);
        setProjects((prev) =>
          prev.map((p) => (p.id === activeIdRef.current ? { ...p, has_report: true, status: "ready" } : p))
        );
        break;
      case "chat_token":
        setChatStatus(null);
        setLiveAssistant((prev) => (prev ?? "") + e.token);
        break;
      case "chat_done":
        setChatStatus(null);
        break;
      case "error":
        setLiveStatus(null);
        setChatStatus(null);
        break;
      case "voice_state":
        setVoiceState(e.state);
        break;
      case "voice_audio":
        setVoiceAudio({ b64: e.audio, id: e.id });
        break;
    }
  }, []);

  // Switch active project: load its state + (re)open a socket.
  useEffect(() => {
    if (!activeId) return;
    let cancelled = false;
    socketRef.current?.close();
    setLiveAssistant(null);
    setLiveStatus(null);
    setChatStatus(null);
    setVoiceEnabled(false);
    setVoiceState("idle");
    setVoiceAudio(null);

    (async () => {
      let full: ProjectFull;
      try {
        full = await api.getProject(activeId);
      } catch {
        return;
      }
      if (cancelled) return;
      setMessages(full.messages);
      setReport(full.report);
      setStatus(full.status);
      setFilename(full.filename);
    })();

    const sock = new ProjectSocket(activeId, handleEvent);
    sock.connect();
    socketRef.current = sock;
    return () => {
      cancelled = true;
      sock.close();
    };
  }, [activeId, handleEvent]);

  const onNewProject = async () => {
    const p = await api.createProject();
    await refreshProjects();
    setActiveId(p.id);
    setNavOpen(false);
    setCanvasOpen(false);
  };

  const onSelect = (id: string) => {
    setActiveId(id);
    setNavOpen(false);
    setCanvasOpen(false);
  };

  const onRename = async (id: string, name: string) => {
    setProjects((prev) => prev.map((p) => (p.id === id ? { ...p, name } : p)));
    try {
      await api.renameProject(id, name);
    } catch {
      await refreshProjects();
    }
  };

  const onDelete = async (id: string) => {
    await api.deleteProject(id);
    const list = await refreshProjects();
    if (id === activeId) {
      if (list.length) setActiveId(list[0].id);
      else onNewProject();
    }
  };

  const onUpload = async (file: File) => {
    if (!activeId) return;
    setStatus("running");
    setFilename(file.name);
    try {
      await api.upload(activeId, file);
    } catch (err) {
      setStatus("error");
      alert(`Upload failed: ${(err as Error).message}`);
    }
  };

  const onSend = (content: string) => socketRef.current?.sendChat(content);

  // --- voice ---------------------------------------------------------------
  const onToggleVoice = async () => {
    if (voiceEnabled) {
      setVoiceEnabled(false);
      setVoiceState("idle");
      return;
    }
    setVoiceWarming(true);
    try {
      const res = await api.voiceWarmup();
      if (!res.ok) {
        alert(`Voice unavailable: ${res.detail}`);
        return;
      }
      setVoiceState("idle");
      setVoiceEnabled(true);
    } catch (err) {
      alert(`Could not start voice: ${(err as Error).message}`);
    } finally {
      setVoiceWarming(false);
    }
  };

  const { phase: micPhase, level: micLevel } = useVoice({
    enabled: voiceEnabled,
    serverState: voiceState,
    audio: voiceAudio,
    onUtterance: (b64) => socketRef.current?.sendVoice(b64),
    onError: (msg) => {
      setVoiceEnabled(false);
      alert(msg);
    },
  });

  const activeProject = projects.find((p) => p.id === activeId) ?? null;
  const showEmptyState = status === "empty" && !report && messages.length === 0;
  const busy = status === "running" || status === "queued";

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-void text-primary">
      {/* Sidebar (drawer on small screens) */}
      {navOpen && (
        <div className="fixed inset-0 z-30 bg-black/50 lg:hidden" onClick={() => setNavOpen(false)} />
      )}
      <div
        className={`fixed z-40 h-full lg:static lg:z-auto transition-transform lg:translate-x-0 ${
          navOpen ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <Sidebar
          projects={projects}
          activeId={activeId}
          onSelect={onSelect}
          onNew={onNewProject}
          onDelete={onDelete}
          onRename={onRename}
          health={health}
        />
      </div>

      {/* Center column */}
      <main className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-3 border-b border-hairline px-4 py-3">
          <button
            className="rounded-md p-1.5 text-muted hover:bg-raised hover:text-primary lg:hidden"
            onClick={() => setNavOpen(true)}
            aria-label="Open projects"
          >
            <Menu size={18} />
          </button>
          <div className="min-w-0 flex-1">
            <h1 className="truncate font-display text-[15px] font-600 text-primary">
              {activeProject ? (
                <EditableTitle
                  value={activeProject.name}
                  onCommit={(name) => onRename(activeProject.id, name)}
                  inputClassName="font-display text-[15px] font-600 w-full max-w-[320px]"
                  title="Click to rename this project"
                />
              ) : (
                "…"
              )}
            </h1>
            {activeProject && (
              <p className="truncate font-mono text-[11px] text-muted">
                {filename ?? "no file yet"} · {status}
              </p>
            )}
          </div>
          {report && (
            <button
              className="flex items-center gap-1.5 rounded-md border border-hairline px-2.5 py-1.5 text-xs text-muted hover:border-azure hover:text-primary xl:hidden"
              onClick={() => setCanvasOpen(true)}
            >
              <PanelRight size={14} /> Panel
            </button>
          )}
        </header>

        <div className="relative flex min-h-0 flex-1 flex-col">
          {showEmptyState ? (
            <UploadDropzone onUpload={onUpload} />
          ) : (
            <>
              <ChatThread
                messages={messages}
                liveAssistant={liveAssistant}
                liveStatus={busy ? liveStatus : null}
                chatStatus={chatStatus}
              />
              <div className="px-4 pt-1">
                {report && (
                  <VoiceControl
                    enabled={voiceEnabled}
                    warming={voiceWarming}
                    phase={micPhase}
                    serverState={voiceState}
                    level={micLevel}
                    onToggle={onToggleVoice}
                  />
                )}
              </div>
              <ChatInput onSend={onSend} disabled={!report} placeholder={report ? "Ask about this analysis…" : "Analysis in progress…"} />
            </>
          )}
        </div>
      </main>

      {/* Analysis Canvas — persistent on xl, slide-over below */}
      <aside className="hidden xl:flex xl:w-[440px] xl:shrink-0 xl:flex-col xl:border-l xl:border-hairline">
        <AnalysisCanvas report={report} status={status} liveStatus={liveStatus} projectId={activeId} />
      </aside>

      {canvasOpen && (
        <div className="fixed inset-0 z-40 xl:hidden">
          <div className="absolute inset-0 bg-black/50" onClick={() => setCanvasOpen(false)} />
          <div className="absolute right-0 top-0 flex h-full w-[min(440px,92vw)] flex-col border-l border-hairline bg-surface">
            <button
              className="absolute right-3 top-3 z-10 rounded-md p-1.5 text-muted hover:bg-raised hover:text-primary"
              onClick={() => setCanvasOpen(false)}
              aria-label="Close panel"
            >
              <X size={18} />
            </button>
            <AnalysisCanvas report={report} status={status} liveStatus={liveStatus} projectId={activeId} />
          </div>
        </div>
      )}
    </div>
  );
}
