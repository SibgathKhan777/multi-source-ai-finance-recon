"use client";

import { useEffect, useState } from "react";
import { acknowledgeException, getExceptionDetail, type ExceptionDetail } from "@/lib/api";
import { TypeBadge, StatusPill, OwnerTag } from "./StatusBadge";

const SOURCE_ORDER = ["ledger", "psp", "bank"];
const SOURCE_LABELS: Record<string, string> = { ledger: "Ledger", psp: "PSP export", bank: "Bank statement" };

export default function ExceptionDetailPanel({
  exceptionId,
  onClose,
  onAcknowledged,
}: {
  exceptionId: string;
  onClose: () => void;
  onAcknowledged: () => void;
}) {
  const [detail, setDetail] = useState<ExceptionDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [acking, setAcking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setDetail(null);
    getExceptionDetail(exceptionId)
      .then((d) => !cancelled && setDetail(d))
      .catch((e) => !cancelled && setError(String(e)))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [exceptionId]);

  async function handleAcknowledge() {
    setAcking(true);
    try {
      const updated = await acknowledgeException(exceptionId);
      setDetail((d) => (d ? { ...d, status: updated.status, acknowledged_at: updated.acknowledged_at, acknowledged_by: updated.acknowledged_by } : d));
      onAcknowledged();
    } catch (e) {
      setError(String(e));
    } finally {
      setAcking(false);
    }
  }

  const recordsBySource = new Map(detail?.records.map((r) => [r.source, r]) ?? []);

  return (
    <aside className="fixed inset-y-0 right-0 z-20 flex w-full max-w-xl flex-col border-l border-slate-200 bg-white shadow-xl dark:border-slate-800 dark:bg-slate-900">
      <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4 dark:border-slate-800">
        <div>
          <p className="font-mono text-xs text-slate-500 dark:text-slate-400">{exceptionId}</p>
          {detail && (
            <div className="mt-1 flex items-center gap-2">
              <TypeBadge type={detail.type} />
              <StatusPill status={detail.status} />
            </div>
          )}
        </div>
        <button
          onClick={onClose}
          className="rounded-md p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-600 dark:hover:bg-slate-800 dark:hover:text-slate-200"
          aria-label="Close"
        >
          ✕
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-5 py-4">
        {loading && <p className="text-sm text-slate-500">Loading…</p>}
        {error && <p className="text-sm text-rose-600">{error}</p>}

        {detail && (
          <>
            <p className="text-sm leading-6 text-slate-700 dark:text-slate-300">{detail.detail}</p>

            <div className="mt-3 flex items-center gap-4 text-sm">
              <span className="text-slate-500 dark:text-slate-400">Suggested owner</span>
              <OwnerTag owner={detail.suggested_owner} />
            </div>

            {detail.acknowledged_by && (
              <p className="mt-1 text-xs text-slate-400">
                Acknowledged by {detail.acknowledged_by} at {detail.acknowledged_at}
              </p>
            )}

            <h3 className="mt-6 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
              Raw records by source
            </h3>
            <div className="mt-2 grid grid-cols-1 gap-3 sm:grid-cols-3">
              {SOURCE_ORDER.map((source) => {
                const rec = recordsBySource.get(source);
                return (
                  <div
                    key={source}
                    className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs dark:border-slate-800 dark:bg-slate-800/40"
                  >
                    <p className="mb-2 font-semibold text-slate-600 dark:text-slate-300">{SOURCE_LABELS[source]}</p>
                    {rec ? (
                      <dl className="space-y-1">
                        <Row label="native id" value={rec.native_id} mono />
                        <Row label="amount" value={String(rec.amount)} />
                        <Row label="currency" value={rec.currency ?? "—"} />
                        <Row label="state" value={rec.state} />
                        {rec.flag_reason && <Row label="flag" value={rec.flag_reason} />}
                        <div className="mt-2 border-t border-slate-200 pt-2 dark:border-slate-700">
                          {rec.raw_payload &&
                            Object.entries(rec.raw_payload).map(([k, v]) => (
                              <Row key={k} label={k} value={v == null ? "—" : String(v)} muted />
                            ))}
                        </div>
                      </dl>
                    ) : (
                      <p className="italic text-slate-400">no record from this source</p>
                    )}
                  </div>
                );
              })}
            </div>
          </>
        )}
      </div>

      {detail && (
        <div className="border-t border-slate-200 px-5 py-4 dark:border-slate-800">
          <button
            onClick={handleAcknowledge}
            disabled={acking || detail.status === "acknowledged"}
            className="w-full rounded-lg bg-slate-900 px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-40 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-white"
          >
            {detail.status === "acknowledged" ? "Acknowledged" : acking ? "Acknowledging…" : "Acknowledge"}
          </button>
        </div>
      )}
    </aside>
  );
}

function Row({ label, value, mono, muted }: { label: string; value: string; mono?: boolean; muted?: boolean }) {
  return (
    <div className="flex justify-between gap-2">
      <dt className={`text-slate-400 ${muted ? "" : ""}`}>{label}</dt>
      <dd className={`text-right ${mono ? "font-mono" : ""} ${muted ? "text-slate-500 dark:text-slate-400" : "text-slate-700 dark:text-slate-200"}`}>
        {value}
      </dd>
    </div>
  );
}
