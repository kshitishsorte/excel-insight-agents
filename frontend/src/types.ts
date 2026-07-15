export type ProjectStatus = "empty" | "queued" | "running" | "ready" | "error";

export interface ProjectSummary {
  id: string;
  name: string;
  created_at: number;
  status: ProjectStatus;
  has_report: boolean;
}

export type MsgRole = "user" | "assistant" | "agent" | "system";
export type MsgKind = "chat" | "status" | "system";

export interface AnalysisTable {
  columns: string[];
  rows: (string | number | null)[][];
  truncated?: boolean;
}

export interface AnalysisResult {
  code: string;
  table: AnalysisTable | null;
  value: string | null;
  error?: string | null;
}

export interface Message {
  id: string;
  role: MsgRole;
  content: string;
  kind: MsgKind;
  ts: number;
  analysis?: AnalysisResult;
}

export interface ProjectFull extends ProjectSummary {
  filename: string | null;
  messages: Message[];
  report: Report | null;
  error: string | null;
}

export interface DtypeChange {
  column: string;
  dtype_before: string;
  dtype_after: string;
  changed: boolean;
}

export interface Overview {
  rows_before: number;
  rows_after: number;
  cols_before: number;
  cols_after: number;
  n_dtype_changed: number;
  total_cells_imputed: number;
  total_rows_dropped: number;
  dtype_changes: DtypeChange[];
  final_approved: boolean;
  n_rounds: number;
  column_failures: string[];
  models: Record<string, string | boolean>;
}

export interface VerifierIssue {
  column: string;
  problem: string;
  suggested_fix: string;
}

export interface VerificationRound {
  round_no: number;
  approved: boolean;
  issues: VerifierIssue[];
  revised_columns: string[];
  error: string;
}

export interface Verification {
  final_approved: boolean;
  n_rounds: number;
  unresolved_issues: VerifierIssue[];
  rounds: VerificationRound[];
  notes: string[];
  column_failures: string[];
}

export interface Finding {
  category: string;
  icon: string;
  title: string;
  detail: string;
  severity: "info" | "good" | "warn" | "bad";
}

export interface ChartPayload {
  key: string;
  figure?: { data: unknown[]; layout: Record<string, unknown> };
  error?: string;
}

export interface Eda {
  narrative: string;
  findings: Finding[];
  takeaways: string[];
  numeric_cols: string[];
  categorical_cols: string[];
  datetime_cols: string[];
  top_correlations: Record<string, unknown>[];
  skewness: Record<string, number | null>;
  outlier_summary: Record<string, Record<string, number | null>>;
  describe: Record<string, Record<string, number | null>>;
  charts: ChartPayload[];
}

export interface Report {
  overview: Overview;
  cleaning_log: Record<string, unknown>[];
  missing_summary: Record<string, unknown>[];
  verification: Verification;
  eda: Eda;
}

// WebSocket server -> client events
export type WsEvent =
  | { type: "status"; stage: string; detail: string; round?: number; max_rounds?: number }
  | { type: "message"; message: Message }
  | { type: "report_ready"; report: Report }
  | { type: "chat_status"; detail: string }
  | { type: "chat_token"; token: string }
  | { type: "chat_done" }
  | { type: "error"; detail: string }
  | { type: "status_change"; status: ProjectStatus }
  | { type: "voice_state"; state: VoiceState }
  | { type: "voice_transcript"; text: string }
  | { type: "voice_audio"; audio: string; id: string };

export type VoiceState = "idle" | "transcribing" | "thinking" | "speaking";
