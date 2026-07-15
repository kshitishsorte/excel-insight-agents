import type { ProjectSummary, ProjectFull } from "../types";

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  async health(): Promise<{ ollama_ok: boolean; detail: string }> {
    return json(await fetch("/api/health"));
  },
  async voiceWarmup(): Promise<{ ok: boolean; detail: string }> {
    return json(await fetch("/api/voice/warmup", { method: "POST" }));
  },
  async listProjects(): Promise<ProjectSummary[]> {
    return json(await fetch("/api/projects"));
  },
  async createProject(name?: string): Promise<{ id: string; name: string }> {
    return json(
      await fetch("/api/projects", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name ?? null }),
      })
    );
  },
  async getProject(id: string): Promise<ProjectFull> {
    return json(await fetch(`/api/projects/${id}`));
  },
  async renameProject(id: string, name: string): Promise<ProjectSummary> {
    return json(
      await fetch(`/api/projects/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      })
    );
  },
  async deleteProject(id: string): Promise<void> {
    await json(await fetch(`/api/projects/${id}`, { method: "DELETE" }));
  },
  async upload(id: string, file: File): Promise<{ status: string; filename: string }> {
    const form = new FormData();
    form.append("file", file);
    return json(await fetch(`/api/projects/${id}/upload`, { method: "POST", body: form }));
  },
  downloadCleanedUrl(id: string): string {
    return `/api/projects/${id}/download/cleaned`;
  },
  downloadReportUrl(id: string): string {
    return `/api/projects/${id}/download/report`;
  },
};
