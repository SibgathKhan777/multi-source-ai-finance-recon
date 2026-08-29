const TYPE_STYLES: Record<string, string> = {
  conflicting: "bg-rose-50 text-rose-700 ring-rose-600/20 dark:bg-rose-950 dark:text-rose-300 dark:ring-rose-400/30",
  orphan: "bg-amber-50 text-amber-700 ring-amber-600/20 dark:bg-amber-950 dark:text-amber-300 dark:ring-amber-400/30",
  partial: "bg-sky-50 text-sky-700 ring-sky-600/20 dark:bg-sky-950 dark:text-sky-300 dark:ring-sky-400/30",
  disputed: "bg-violet-50 text-violet-700 ring-violet-600/20 dark:bg-violet-950 dark:text-violet-300 dark:ring-violet-400/30",
  unmatched: "bg-slate-100 text-slate-700 ring-slate-600/20 dark:bg-slate-800 dark:text-slate-300 dark:ring-slate-400/30",
};

const STATUS_STYLES: Record<string, string> = {
  new: "bg-rose-50 text-rose-700 ring-rose-600/20 dark:bg-rose-950 dark:text-rose-300 dark:ring-rose-400/30",
  acknowledged: "bg-emerald-50 text-emerald-700 ring-emerald-600/20 dark:bg-emerald-950 dark:text-emerald-300 dark:ring-emerald-400/30",
};

function Badge({ label, className }: { label: string; className: string }) {
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset ${className}`}>
      {label}
    </span>
  );
}

export function TypeBadge({ type }: { type: string }) {
  return <Badge label={type} className={TYPE_STYLES[type] ?? TYPE_STYLES.unmatched} />;
}

export function StatusPill({ status }: { status: string }) {
  return <Badge label={status} className={STATUS_STYLES[status] ?? STATUS_STYLES.new} />;
}

export function OwnerTag({ owner }: { owner: string }) {
  const isEngineering = owner === "engineering";
  return (
    <span
      className={`inline-flex items-center gap-1.5 text-xs font-medium ${
        isEngineering ? "text-indigo-700 dark:text-indigo-300" : "text-teal-700 dark:text-teal-300"
      }`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${isEngineering ? "bg-indigo-500" : "bg-teal-500"}`} />
      {owner}
    </span>
  );
}
