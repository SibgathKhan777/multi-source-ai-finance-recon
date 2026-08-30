"use client";

import { useCallback, useEffect, useState } from "react";
import { getReport, listExceptions, type Report, type ExceptionSummary } from "@/lib/api";
import TopNav from "@/components/TopNav";
import SummaryCards from "@/components/SummaryCards";
import ExceptionsTable from "@/components/ExceptionsTable";
import ExceptionDetailPanel from "@/components/ExceptionDetailPanel";

type StatusFilter = "all" | "new" | "acknowledged";

export default function SolutionPage() {
  const [report, setReport] = useState<Report | null>(null);
  const [exceptions, setExceptions] = useState<ExceptionSummary[]>([]);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const [r, e] = await Promise.all([getReport(), listExceptions()]);
      setReport(r);
      setExceptions(e);
      setError(null);
    } catch (err) {
      setError(
        `Could not reach the API at ${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}. ` +
          "Is the FastAPI backend running? (" + String(err) + ")"
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const filtered = exceptions.filter((e) => statusFilter === "all" || e.status === statusFilter);

  return (
    <div className="min-h-screen bg-slate-50 dark:bg-slate-950">
      <TopNav active="solution" />

      <header className="border-b border-slate-200 bg-white px-6 py-5 dark:border-slate-800 dark:bg-slate-900">
        <p className="text-xs font-semibold uppercase tracking-wide text-teal-700 dark:text-teal-400">
          The solution
        </p>
        <h1 className="mt-1 text-lg font-semibold text-slate-900 dark:text-slate-50">
          Multi-Source Finance Reconciliation
        </h1>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          The same three sources you just saw disagree — ingested, matched by rules, resolved by an agent where it
          can be, and routed to a human for exactly the rest.
        </p>
      </header>

      <main className="mx-auto max-w-6xl px-6 py-8">
        {error && (
          <div className="mb-6 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-300">
            {error}
          </div>
        )}

        {loading && !report && <p className="text-sm text-slate-500">Loading reconciliation report…</p>}

        {report && (
          <>
            <SummaryCards report={report} />

            <div className="mt-8 flex items-center justify-between">
              <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
                Exceptions
              </h2>
              <div className="flex gap-1 rounded-lg border border-slate-200 bg-white p-1 dark:border-slate-800 dark:bg-slate-900">
                {(["all", "new", "acknowledged"] as StatusFilter[]).map((s) => (
                  <button
                    key={s}
                    onClick={() => setStatusFilter(s)}
                    className={`rounded-md px-3 py-1 text-xs font-medium transition-colors ${
                      statusFilter === s
                        ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900"
                        : "text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-100"
                    }`}
                  >
                    {s === "all" ? "All" : s === "new" ? "New" : "Acknowledged"}
                  </button>
                ))}
              </div>
            </div>

            <div className="mt-3">
              <ExceptionsTable exceptions={filtered} selectedId={selectedId} onSelect={setSelectedId} />
            </div>
          </>
        )}
      </main>

      {selectedId && (
        <ExceptionDetailPanel
          exceptionId={selectedId}
          onClose={() => setSelectedId(null)}
          onAcknowledged={refresh}
        />
      )}
    </div>
  );
}
