import { useEffect, useState } from "react";
import { Download, Loader2, LayoutGrid } from "lucide-react";
import type { ProjectStatus, Report } from "../types";
import { api } from "../lib/api";
import { Overview } from "./ReportTabs/Overview";
import { CleaningLog } from "./ReportTabs/CleaningLog";
import { VerificationHistory } from "./ReportTabs/VerificationHistory";
import { EdaInsights } from "./ReportTabs/EdaInsights";

interface LiveStatus {
  detail: string;
  round?: number;
  max_rounds?: number;
}

const TABS = ["Overview", "Cleaning Log", "Verification", "EDA & Insights"] as const;
type Tab = (typeof TABS)[number];

export function AnalysisCanvas({
  report,
  status,
  liveStatus,
  projectId,
}: {
  report: Report | null;
  status: ProjectStatus;
  liveStatus: LiveStatus | null;
  projectId: string | null;
}) {
  const [tab, setTab] = useState<Tab>("Overview");
  const busy = status === "running" || status === "queued";
  const glow = busy ? "active" : report ? "resting" : "resting";

  // When a fresh report lands, jump back to Overview.
  useEffect(() => {
    if (report) setTab("Overview");
  }, [report]);

  return (
    <div className="flex h-full flex-col p-3">
      <div className={`canvas-glow ${glow} flex min-h-0 flex-1 flex-col overflow-hidden`}>
        {/* Header */}
        <div className="flex items-center gap-2 border-b border-hairline px-4 py-3">
          <LayoutGrid size={15} className="text-azure" />
          <span className="font-display text-[13px] font-600 tracking-wide text-primary">
            Analysis Canvas
          </span>
          <div className="flex-1" />
          {report && projectId && (
            <div className="flex items-center gap-1">
              <a
                href={api.downloadCleanedUrl(projectId)}
                className="flex items-center gap-1 rounded-md px-2 py-1 text-[11px] text-muted hover:bg-raised hover:text-primary"
                title="Download cleaned .xlsx"
              >
                <Download size={12} /> xlsx
              </a>
              <a
                href={api.downloadReportUrl(projectId)}
                className="flex items-center gap-1 rounded-md px-2 py-1 text-[11px] text-muted hover:bg-raised hover:text-primary"
                title="Download HTML report"
              >
                <Download size={12} /> html
              </a>
            </div>
          )}
        </div>

        {report ? (
          <>
            <div className="flex gap-1 overflow-x-auto border-b border-hairline px-2 py-2">
              {TABS.map((t) => (
                <button
                  key={t}
                  onClick={() => setTab(t)}
                  className={`whitespace-nowrap rounded-md px-2.5 py-1.5 text-[12px] font-500 transition-colors ${
                    tab === t ? "bg-raised text-primary" : "text-muted hover:text-primary"
                  }`}
                >
                  {t}
                </button>
              ))}
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
              {tab === "Overview" && <Overview report={report} />}
              {tab === "Cleaning Log" && <CleaningLog report={report} />}
              {tab === "Verification" && <VerificationHistory report={report} />}
              {tab === "EDA & Insights" && <EdaInsights report={report} />}
            </div>
          </>
        ) : (
          <div className="flex flex-1 flex-col items-center justify-center px-6 text-center">
            {busy ? (
              <>
                <Loader2 size={26} className="mb-4 animate-spin text-aqua motion-reduce:animate-none" />
                <p className="font-display text-sm font-500 text-primary">
                  {status === "queued" ? "Queued…" : "Agents at work"}
                </p>
                <p className="mt-2 max-w-[240px] font-mono text-[11.5px] leading-relaxed text-muted">
                  {liveStatus?.detail ?? "Starting the pipeline…"}
                </p>
                {liveStatus?.round && (
                  <div className="mt-4 flex gap-1.5">
                    {Array.from({ length: liveStatus.max_rounds ?? 3 }).map((_, i) => (
                      <span
                        key={i}
                        className={`h-1.5 w-6 rounded-full ${
                          i < (liveStatus.round ?? 0) ? "bg-azure" : "bg-hairline"
                        }`}
                      />
                    ))}
                  </div>
                )}
              </>
            ) : (
              <p className="max-w-[220px] text-[13px] text-muted">
                Your analysis will appear here once a spreadsheet is processed.
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
