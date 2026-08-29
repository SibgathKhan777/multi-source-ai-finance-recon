const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export type MatchGroupStatusCounts = Record<string, number>;

export interface Report {
  generated_at: string;
  match_rate: number;
  total_canonical_records: number;
  matched_canonical_records: number;
  match_group_status_counts: MatchGroupStatusCounts;
  exception_counts_by_type: Record<string, number>;
  exception_counts_by_status: Record<string, number>;
  unresolved_exceptions: ExceptionSummary[];
  all_exceptions: ExceptionSummary[];
}

export interface ExceptionSummary {
  exception_id: string;
  type: string;
  detail: string;
  status: string;
  suggested_owner: string;
  canonical_ids?: string[];
  created_at?: string;
  acknowledged_at?: string | null;
  acknowledged_by?: string | null;
}

export interface ExceptionRecord {
  canonical_id: string;
  source: string;
  native_id: string;
  amount: number;
  currency: string | null;
  counterparty_id: string | null;
  state: string;
  raw_payload: Record<string, unknown> | null;
  validation_status: string | null;
  flag_reason: string | null;
}

export interface ExceptionDetail extends ExceptionSummary {
  records: ExceptionRecord[];
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(`${path} failed: ${res.status} ${res.statusText}`);
  }
  return res.json();
}

export function getReport() {
  return apiFetch<Report>("/api/report");
}

export function listExceptions() {
  return apiFetch<ExceptionSummary[]>("/api/exceptions");
}

export function getExceptionDetail(id: string) {
  return apiFetch<ExceptionDetail>(`/api/exceptions/${id}`);
}

export function acknowledgeException(id: string, acknowledgedBy = "finance_ops_user") {
  return apiFetch<ExceptionSummary>(`/api/exceptions/${id}/acknowledge`, {
    method: "POST",
    body: JSON.stringify({ acknowledged_by: acknowledgedBy }),
  });
}
