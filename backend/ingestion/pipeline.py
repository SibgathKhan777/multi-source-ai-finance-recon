"""Phase 1 — multi-source ingestion: adapters -> validation -> dedup -> raw store."""
import hashlib
from datetime import datetime, timezone

from database import get_session
from models import RawRecord, DuplicateSkip, IngestionRun
from ingestion.adapters import ADAPTERS
from config import LEDGER_CSV, PSP_CSV, BANK_CSV


def _max_raw_id_n(session) -> int:
    last = (
        session.query(RawRecord.raw_id)
        .order_by(RawRecord.raw_id.desc())
        .first()
    )
    return int(last[0].split("-")[1]) if last else 0


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _new_run_id():
    return f"RUN-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')}"


def _date_part(source: str, row: dict) -> str:
    ts = row.get("ts_raw") or ""
    if not ts:
        return ""
    if source in ("ledger", "psp"):
        # "2026-08-19T12:00:00+05:30" or "2026-08-19 06:30:00 UTC" or date-only
        return ts[:10]
    if source == "bank":
        # "19-08-2026" dd-mm-yyyy
        parts = ts.split("-")
        if len(parts) == 3:
            return f"{parts[2]}-{parts[1]}-{parts[0]}"
        return ts
    return ts


def _amount_part(row: dict) -> str:
    raw = row.get("amount_raw")
    try:
        return f"{float(raw):.2f}"
    except (TypeError, ValueError):
        return str(raw)


def make_dedup_key(source: str, row: dict) -> str:
    native_id = row.get("native_id") or ""
    amount = _amount_part(row)
    date = _date_part(source, row)
    payload = f"{source}|{native_id}|{amount}|{date}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def run_ingestion(sources=None, look_back_days=7, session=None):
    """Runs the full ingestion pass for the given sources (default: all 3).

    Returns a summary dict. Duplicate rows (by dedup_key) are skipped and
    logged, never inserted twice; never errors on a duplicate.
    """
    own_session = session is None
    session = session or get_session()
    sources = sources or {"ledger": LEDGER_CSV, "psp": PSP_CSV, "bank": BANK_CSV}

    run_id = _new_run_id()
    session.add(
        IngestionRun(
            run_id=run_id,
            started_at=_now_iso(),
            look_back_days=look_back_days,
        )
    )
    session.flush()

    key_to_raw_id = {
        row.dedup_key: row.raw_id
        for row in session.query(RawRecord.dedup_key, RawRecord.raw_id).all()
    }
    next_n = _max_raw_id_n(session)

    processed = 0
    duplicates = 0
    flagged = 0
    inserted_raw_ids = []

    for source, path in sources.items():
        adapter = ADAPTERS[source]
        for row in adapter(path):
            processed += 1
            dedup_key = make_dedup_key(source, row)

            if dedup_key in key_to_raw_id:
                duplicates += 1
                session.add(
                    DuplicateSkip(
                        source=source,
                        native_id=row.get("native_id"),
                        dedup_key=dedup_key,
                        ingestion_run_id=run_id,
                        original_raw_id=key_to_raw_id[dedup_key],
                        skipped_at=_now_iso(),
                    )
                )
                continue

            next_n += 1
            raw_id = f"RAW-{next_n:05d}"
            key_to_raw_id[dedup_key] = raw_id
            if row["validation_status"] == "flagged":
                flagged += 1

            raw_payload = {
                "native_id": row.get("native_id"),
                "amount": row.get("amount_raw"),
                "currency": row.get("currency_raw"),
                "ts": row.get("ts_raw"),
                "counterparty": row.get("counterparty_raw"),
                **(row.get("extra") or {}),
            }

            session.add(
                RawRecord(
                    raw_id=raw_id,
                    source=source,
                    ingestion_run_id=run_id,
                    dedup_key=dedup_key,
                    native_id=row.get("native_id") or "",
                    validation_status=row["validation_status"],
                    flag_reason=row["flag_reason"],
                    raw_payload=raw_payload,
                    ingested_at=_now_iso(),
                )
            )
            inserted_raw_ids.append(raw_id)

    run = session.get(IngestionRun, run_id)
    run.rows_processed = processed
    run.duplicates_skipped = duplicates
    run.flagged_rows = flagged

    if own_session:
        session.commit()

    return {
        "run_id": run_id,
        "rows_processed": processed,
        "rows_inserted": len(inserted_raw_ids),
        "duplicates_skipped": duplicates,
        "flagged_rows": flagged,
        "inserted_raw_ids": inserted_raw_ids,
    }
