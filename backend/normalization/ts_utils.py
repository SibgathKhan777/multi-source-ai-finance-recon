"""Timestamp normalization: every source timestamp is converted to a
timezone-aware UTC datetime before any comparison happens. This is what
makes story 19 (same instant, logged as IST / UTC / date-only) resolve
correctly instead of showing up as a false conflict.
"""
from datetime import datetime, timezone


def normalize_ledger_ts(ts_raw: str):
    """'2026-08-14T10:32:00+05:30' (exact) or '2026-08-20' (date-only)."""
    if not ts_raw:
        return None, "missing"
    if "T" in ts_raw:
        dt = datetime.fromisoformat(ts_raw)
        return dt.astimezone(timezone.utc), "exact"
    dt = datetime.fromisoformat(ts_raw)  # date-only -> midnight, naive
    return dt.replace(tzinfo=timezone.utc), "date_only"


def normalize_psp_ts(ts_raw: str):
    """'2026-08-14 05:02:00 UTC' — always exact and already UTC."""
    if not ts_raw:
        return None, "missing"
    cleaned = ts_raw.replace(" UTC", "").strip()
    dt = datetime.strptime(cleaned, "%Y-%m-%d %H:%M:%S")
    return dt.replace(tzinfo=timezone.utc), "exact"


def normalize_bank_ts(date_raw: str):
    """'14-08-2026' dd-mm-yyyy — always date-only."""
    if not date_raw:
        return None, "missing"
    dt = datetime.strptime(date_raw.strip(), "%d-%m-%Y")
    return dt.replace(tzinfo=timezone.utc), "date_only"


NORMALIZERS = {
    "ledger": normalize_ledger_ts,
    "psp": normalize_psp_ts,
    "bank": normalize_bank_ts,
}
