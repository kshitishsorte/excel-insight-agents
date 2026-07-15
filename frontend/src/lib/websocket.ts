import type { WsEvent } from "../types";

/**
 * One WebSocket per project. Same-origin URL works in dev (Vite proxies /ws)
 * and in single-process production (FastAPI serves everything on one port).
 */
export class ProjectSocket {
  private ws: WebSocket | null = null;
  private closedByUs = false;

  constructor(
    private projectId: string,
    private onEvent: (e: WsEvent) => void,
    private onOpen?: () => void
  ) {}

  connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    this.ws = new WebSocket(`${proto}://${location.host}/ws/projects/${this.projectId}`);
    this.ws.onopen = () => this.onOpen?.();
    this.ws.onmessage = (ev) => {
      try {
        this.onEvent(JSON.parse(ev.data) as WsEvent);
      } catch {
        /* ignore malformed frames */
      }
    };
    this.ws.onclose = () => {
      // Auto-reconnect unless we intentionally closed (project switch/unmount).
      if (!this.closedByUs) setTimeout(() => this.connect(), 1200);
    };
  }

  sendChat(content: string) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: "chat", content }));
    }
  }

  sendVoice(audioB64: string) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: "voice", audio: audioB64 }));
    }
  }

  close() {
    this.closedByUs = true;
    this.ws?.close();
    this.ws = null;
  }
}
