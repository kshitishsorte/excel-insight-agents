import { CheckCircle2, AlertTriangle } from "lucide-react";
import type { Report } from "../../types";

function Stat({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="rounded-xl border border-hairline bg-surface px-3 py-2.5">
      <div className="font-mono text-lg font-500 text-primary">{value}</div>
      <div className="mt-0.5 text-[11px] text-muted">{label}</div>
      {sub && <div className="font-mono text-[10px] text-muted">{sub}</div>}
    </div>
  );
}

export function Overview({ report }: { report: Report }) {
  const o = report.overview;
  return (
    <div className="flex flex-col gap-4">
      {o.final_approved ? (
        <div className="flex items-center gap-2 rounded-lg border border-aqua/30 bg-aqua/10 px-3 py-2 text-[12.5px] text-aqua">
          <CheckCircle2 size={15} /> Verifier approved after {o.n_rounds} round(s)
        </div>
      ) : (
        <div className="flex items-center gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-[12.5px] text-amber-300">
          <AlertTriangle size={15} /> Not fully approved after {o.n_rounds} round(s) — see Verification
        </div>
      )}

      <div className="grid grid-cols-2 gap-2">
        <Stat label="Rows" value={o.rows_after} sub={`was ${o.rows_before}`} />
        <Stat label="Columns" value={o.cols_after} sub={`was ${o.cols_before}`} />
        <Stat label="Types corrected" value={o.n_dtype_changed} />
        <Stat label="Cells imputed" value={o.total_cells_imputed} />
      </div>

      {o.total_rows_dropped > 0 && (
        <p className="text-[12px] text-muted">{o.total_rows_dropped} row(s) dropped.</p>
      )}

      {o.column_failures.length > 0 && (
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-[12px] text-amber-300">
          Fallback rules used for: {o.column_failures.join(", ")}
        </div>
      )}

      <div>
        <h4 className="mb-2 text-[12px] font-600 uppercase tracking-wide text-muted">Type changes</h4>
        <div className="overflow-hidden rounded-lg border border-hairline">
          <table className="w-full text-[12px]">
            <tbody>
              {o.dtype_changes.map((d) => (
                <tr key={d.column} className="border-b border-hairline last:border-0">
                  <td className="px-3 py-1.5 text-primary">{d.column}</td>
                  <td className="px-3 py-1.5 text-right font-mono text-muted">
                    {d.changed ? (
                      <span className="text-primary">
                        {d.dtype_before} → {d.dtype_after}
                      </span>
                    ) : (
                      <span>{d.dtype_after}</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <p className="font-mono text-[11px] text-muted">
        cleaner {String(o.models.cleaner)} · verifier {String(o.models.verifier)}
      </p>
    </div>
  );
}
