import type { Report } from "@/lib/api";

function Card({ label, value, accent }: { label: string; value: string; accent?: string }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
      <p className="text-xs font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">{label}</p>
      <p className={`mt-2 text-2xl font-semibold tabular-nums ${accent ?? "text-slate-900 dark:text-slate-50"}`}>
        {value}
      </p>
    </div>
  );
}

const STATUS_LABELS: Record<string, string> = {
  matched: "Matched",
  partial: "Partial",
  unmatched: "Unmatched",
  disputed: "Disputed",
};

export default function SummaryCards({ report }: { report: Report }) {
  const matchRatePct = (report.match_rate * 100).toFixed(1);

  return (
    <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
      <Card
        label="Match rate"
        value={`${matchRatePct}%`}
        accent={report.match_rate >= 0.75 ? "text-emerald-600 dark:text-emerald-400" : "text-amber-600 dark:text-amber-400"}
      />
      <Card label="Canonical records" value={String(report.total_canonical_records)} />
      {Object.entries(report.match_group_status_counts).map(([status, count]) => (
        <Card key={status} label={STATUS_LABELS[status] ?? status} value={String(count)} />
      ))}
    </div>
  );
}
