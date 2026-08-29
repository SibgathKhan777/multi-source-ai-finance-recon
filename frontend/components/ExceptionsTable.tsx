"use client";

import { useMemo, useState } from "react";
import type { ExceptionSummary } from "@/lib/api";
import { TypeBadge, StatusPill, OwnerTag } from "./StatusBadge";

type SortKey = "exception_id" | "type" | "suggested_owner" | "status";

export default function ExceptionsTable({
  exceptions,
  selectedId,
  onSelect,
}: {
  exceptions: ExceptionSummary[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const [sortKey, setSortKey] = useState<SortKey>("exception_id");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");

  const sorted = useMemo(() => {
    const copy = [...exceptions];
    copy.sort((a, b) => {
      const av = a[sortKey] ?? "";
      const bv = b[sortKey] ?? "";
      const cmp = String(av).localeCompare(String(bv));
      return sortDir === "asc" ? cmp : -cmp;
    });
    return copy;
  }, [exceptions, sortKey, sortDir]);

  function toggleSort(key: SortKey) {
    if (key === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
  }

  function SortHeader({ label, sortKeyValue }: { label: string; sortKeyValue: SortKey }) {
    const active = sortKey === sortKeyValue;
    return (
      <th
        scope="col"
        className="cursor-pointer select-none px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200"
        onClick={() => toggleSort(sortKeyValue)}
      >
        <span className="inline-flex items-center gap-1">
          {label}
          {active && <span>{sortDir === "asc" ? "↑" : "↓"}</span>}
        </span>
      </th>
    );
  }

  return (
    <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900">
      <table className="w-full border-collapse text-sm">
        <thead className="border-b border-slate-200 dark:border-slate-800">
          <tr>
            <SortHeader label="Exception" sortKeyValue="exception_id" />
            <SortHeader label="Type" sortKeyValue="type" />
            <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
              Reason
            </th>
            <SortHeader label="Owner" sortKeyValue="suggested_owner" />
            <SortHeader label="Status" sortKeyValue="status" />
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
          {sorted.map((exc) => (
            <tr
              key={exc.exception_id}
              onClick={() => onSelect(exc.exception_id)}
              className={`cursor-pointer transition-colors hover:bg-slate-50 dark:hover:bg-slate-800/60 ${
                selectedId === exc.exception_id ? "bg-slate-50 dark:bg-slate-800/60" : ""
              }`}
            >
              <td className="whitespace-nowrap px-4 py-3 font-mono text-xs text-slate-600 dark:text-slate-400">
                {exc.exception_id}
              </td>
              <td className="whitespace-nowrap px-4 py-3">
                <TypeBadge type={exc.type} />
              </td>
              <td className="max-w-md truncate px-4 py-3 text-slate-700 dark:text-slate-300" title={exc.detail}>
                {exc.detail}
              </td>
              <td className="whitespace-nowrap px-4 py-3">
                <OwnerTag owner={exc.suggested_owner} />
              </td>
              <td className="whitespace-nowrap px-4 py-3">
                <StatusPill status={exc.status} />
              </td>
            </tr>
          ))}
          {sorted.length === 0 && (
            <tr>
              <td colSpan={5} className="px-4 py-8 text-center text-slate-400">
                No exceptions match this filter.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
