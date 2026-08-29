"""Phase 2 — normalization, crosswalk resolution, and record lifecycle."""
import re
from datetime import datetime, timezone

from database import get_session
from models import RawRecord, CanonicalRecord
from normalization.crosswalk import seed_crosswalk, resolve_counterparty
from normalization.ts_utils import NORMALIZERS
from config import DEFAULT_CURRENCY

BATCH_ID_RE = re.compile(r"(BATCH-\d+)")


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _next_canonical_n(session) -> int:
    last = (
        session.query(CanonicalRecord.canonical_id)
        .order_by(CanonicalRecord.canonical_id.desc())
        .first()
    )
    return int(last[0].split("-")[1]) if last else 0


def _derive_event_type(source: str, payload: dict) -> str:
    if source == "psp":
        et = (payload.get("event_type") or "payment").lower()
        state = (payload.get("state") or "").lower()
        if "dispute" in state:
            return "chargeback"
        if et == "refund":
            return "refund"
        return "payment"

    if source == "bank":
        narration = (payload.get("narration") or "").lower()
        if "chargeback" in narration:
            return "chargeback"
        if "refund" in narration:
            return "refund"
        return "settlement"

    # ledger
    notes = (payload.get("notes") or "").lower()
    if "chargeback" in notes:
        return "chargeback"
    if "refund" in notes:
        return "refund"
    return "payment"


def _derive_state(source: str, event_type: str) -> str:
    if event_type == "chargeback":
        return "disputed"
    if event_type == "refund":
        return "refunded"
    return {"ledger": "initiated", "psp": "authorized", "bank": "settled"}[source]


def _extract_batch_id(source: str, payload: dict):
    if source == "psp":
        return payload.get("settlement_batch_id") or None
    if source == "ledger":
        notes = payload.get("notes") or ""
        m = BATCH_ID_RE.search(notes)
        return m.group(1) if m else None
    return None


def normalize_record(session, raw: RawRecord, next_n: int) -> CanonicalRecord:
    payload = raw.raw_payload
    source = raw.source

    ts_raw = payload.get("ts")
    ts_utc, ts_precision = NORMALIZERS[source](ts_raw)

    currency_raw = payload.get("currency")
    currency = currency_raw if currency_raw else None

    counterparty_raw = payload.get("counterparty")
    counterparty_id = resolve_counterparty(session, source, counterparty_raw)

    event_type = _derive_event_type(source, payload)
    state = _derive_state(source, event_type)
    settlement_batch_id = _extract_batch_id(source, payload)

    try:
        amount = float(payload.get("amount"))
    except (TypeError, ValueError):
        amount = None

    fee = None
    related_native_id = None
    if source == "psp":
        fee_raw = payload.get("fee")
        try:
            fee = float(fee_raw) if fee_raw not in (None, "") else None
        except ValueError:
            fee = None
        related_native_id = payload.get("related_txn_id") or None

    canonical_id = f"CANON-{next_n:05d}"

    record = CanonicalRecord(
        canonical_id=canonical_id,
        raw_id=raw.raw_id,
        source=source,
        native_id=raw.native_id,
        amount=amount,
        currency=currency,
        currency_inferred=False,
        counterparty_raw=counterparty_raw,
        counterparty_id=counterparty_id,
        ts_utc=ts_utc.replace(tzinfo=None) if ts_utc else None,
        ts_precision=ts_precision,
        event_type=event_type,
        state=state,
        settlement_batch_id=settlement_batch_id,
        fee=fee,
        related_native_id=related_native_id,
        extra={"raw_flag_reason": raw.flag_reason, "validation_status": raw.validation_status},
        match_group_id=None,
        created_at=_now_iso(),
    )
    session.add(record)
    return record


def run_normalization(session=None):
    """Normalizes every raw record that doesn't already have a canonical
    record yet (idempotent — safe to call again after a late-arrival ingest).
    """
    own_session = session is None
    session = session or get_session()

    seed_crosswalk(session=session)

    already_normalized = {
        row[0] for row in session.query(CanonicalRecord.raw_id).all()
    }
    next_n = _next_canonical_n(session)

    created = []
    for raw in session.query(RawRecord).order_by(RawRecord.raw_id).all():
        if raw.raw_id in already_normalized:
            continue
        next_n += 1
        record = normalize_record(session, raw, next_n)
        created.append(record.canonical_id)

    if own_session:
        session.commit()

    return {"canonical_records_created": len(created), "canonical_ids": created}
