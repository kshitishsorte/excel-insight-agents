import Plotly from "plotly.js-dist-min";
import createPlotlyComponent from "react-plotly.js/factory";
import { Lightbulb } from "lucide-react";
import type { Finding, Report } from "../../types";

const Plot = createPlotlyComponent(Plotly);

const SEV_BORDER: Record<Finding["severity"], string> = {
  info: "border-l-azure",
  good: "border-l-aqua",
  warn: "border-l-amber-400",
  bad: "border-l-red-500",
};

export function EdaInsights({ report }: { report: Report }) {
  const eda = report.eda;
  return (
    <div className="flex flex-col gap-4">
      {/* Key findings */}
      {eda.findings.length > 0 && (
        <div className="flex flex-col gap-2">
          {eda.findings.map((f, i) => (
            <div
              key={i}
              className={`rounded-lg border border-hairline border-l-[3px] bg-surface px-3 py-2 ${SEV_BORDER[f.severity]}`}
            >
              <div className="text-[10px] font-600 uppercase tracking-wide text-muted">{f.category}</div>
              <div className="text-[13px] font-600 text-primary">
                {f.icon} {f.title}
              </div>
              <div className="mt-0.5 text-[12px] leading-snug text-muted">{f.detail}</div>
            </div>
          ))}
        </div>
      )}

      {/* Takeaways */}
      {eda.takeaways.length > 0 && (
        <div className="rounded-xl border border-azure/25 bg-azure/5 px-3 py-3">
          <div className="mb-1.5 flex items-center gap-1.5 text-[12px] font-600 text-primary">
            <Lightbulb size={14} className="text-azure" /> Takeaways
          </div>
          <ul className="flex list-disc flex-col gap-1 pl-4">
            {eda.takeaways.map((t, i) => (
              <li key={i} className="text-[12.5px] leading-snug text-muted">
                {t}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Narrative */}
      {eda.narrative && (
        <div>
          <h4 className="mb-1.5 text-[11px] font-600 uppercase tracking-wide text-muted">Narrative</h4>
          <p className="whitespace-pre-wrap text-[13px] leading-relaxed text-primary/90">{eda.narrative}</p>
        </div>
      )}

      {/* Charts */}
      {eda.charts.length > 0 && (
        <div className="flex flex-col gap-3">
          <h4 className="text-[11px] font-600 uppercase tracking-wide text-muted">Charts</h4>
          {eda.charts.map((c) =>
            c.figure ? (
              <div key={c.key} className="overflow-hidden rounded-xl border border-hairline bg-surface p-1">
                <Plot
                  data={c.figure.data as never}
                  layout={{ ...(c.figure.layout as object), autosize: true, height: 260 } as never}
                  config={{ displayModeBar: false, responsive: true } as never}
                  style={{ width: "100%", height: "260px" }}
                  useResizeHandler
                />
              </div>
            ) : (
              <p key={c.key} className="text-[11px] text-muted">
                Chart “{c.key}” could not render.
              </p>
            )
          )}
        </div>
      )}
    </div>
  );
}
