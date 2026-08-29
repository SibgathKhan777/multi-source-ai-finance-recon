"""Source adapters: parse each CSV's native format into a common
intermediate shape without normalizing values (that's Phase 2's job).

Each adapter yields dicts with:
  native_id, amount_raw, currency_raw, ts_raw, counterparty_raw, extra (dict),
  validation_status, flag_reason
"""
import csv
from pathlib import Path


def _read_csv(path: Path):
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            yield row


def _blank(v):
    return v is None or str(v).strip() == ""


def adapt_ledger(path: Path):
    for row in _read_csv(path):
        reasons = []
        native_id = row.get("txn_id")
        amount_raw = row.get("amount")
        currency_raw = row.get("currency")
        ts_raw = row.get("ts")

        if _blank(native_id):
            reasons.append("missing transaction id")
        if _blank(amount_raw):
            reasons.append("missing amount")
        if _blank(currency_raw):
            reasons.append("missing currency field")
        if _blank(ts_raw):
            reasons.append("missing timestamp")
        elif "T" not in ts_raw:
            reasons.append("timestamp truncated to date only")

        try:
            amt = float(amount_raw) if not _blank(amount_raw) else None
        except ValueError:
            amt = None
            reasons.append("unparseable amount")
        if amt is not None and amt < 0:
            reasons.append("negative amount - possible data entry error")

        yield {
            "native_id": native_id,
            "amount_raw": amount_raw,
            "currency_raw": currency_raw,
            "ts_raw": ts_raw,
            "counterparty_raw": row.get("counterparty"),
            "extra": {"notes": row.get("notes") or None},
            "validation_status": "flagged" if reasons else "valid",
            "flag_reason": "; ".join(reasons) if reasons else None,
        }


def adapt_psp(path: Path):
    for row in _read_csv(path):
        reasons = []
        native_id = row.get("payment_id")
        amount_raw = row.get("amt")
        currency_raw = row.get("curr")
        ts_raw = row.get("created_at")

        if _blank(native_id):
            reasons.append("missing payment id")
        if _blank(amount_raw):
            reasons.append("missing amount")
        if _blank(currency_raw):
            reasons.append("missing currency field")
        if _blank(ts_raw):
            reasons.append("missing timestamp")

        try:
            float(amount_raw) if not _blank(amount_raw) else None
        except ValueError:
            reasons.append("unparseable amount")

        yield {
            "native_id": native_id,
            "amount_raw": amount_raw,
            "currency_raw": currency_raw,
            "ts_raw": ts_raw,
            "counterparty_raw": row.get("merchant"),
            "extra": {
                "settlement_batch_id": row.get("settlement_batch_id") or None,
                "fee": row.get("fee"),
                "event_type": row.get("event_type") or None,
                "related_txn_id": row.get("related_txn_id") or None,
                "state": row.get("state") or None,
            },
            "validation_status": "flagged" if reasons else "valid",
            "flag_reason": "; ".join(reasons) if reasons else None,
        }


def adapt_bank(path: Path):
    for row in _read_csv(path):
        reasons = []
        native_id = row.get("ref_no")
        amount_raw = row.get("value")
        ts_raw = row.get("date")

        if _blank(native_id):
            reasons.append("missing reference number")
        if _blank(amount_raw):
            reasons.append("missing amount")
        if _blank(ts_raw):
            reasons.append("missing date")

        try:
            float(amount_raw) if not _blank(amount_raw) else None
        except ValueError:
            reasons.append("unparseable amount")

        yield {
            "native_id": native_id,
            "amount_raw": amount_raw,
            "currency_raw": None,  # bank statement carries no explicit currency column
            "ts_raw": ts_raw,
            "counterparty_raw": row.get("narration"),
            "extra": {"narration": row.get("narration")},
            "validation_status": "flagged" if reasons else "valid",
            "flag_reason": "; ".join(reasons) if reasons else None,
        }


ADAPTERS = {
    "ledger": adapt_ledger,
    "psp": adapt_psp,
    "bank": adapt_bank,
}
