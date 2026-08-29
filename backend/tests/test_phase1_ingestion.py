from ingestion.pipeline import run_ingestion
from models import RawRecord, DuplicateSkip


def test_all_68_rows_processed(db_session):
    summary = run_ingestion(session=db_session)
    db_session.commit()
    assert summary["rows_processed"] == 68
    assert summary["rows_inserted"] == 67  # one LDG-3001 duplicate skipped
    assert summary["duplicates_skipped"] == 1


def test_duplicate_ldg3001_caught(db_session):
    run_ingestion(session=db_session)
    db_session.commit()

    ldg3001_rows = (
        db_session.query(RawRecord)
        .filter(RawRecord.native_id == "LDG-3001")
        .all()
    )
    assert len(ldg3001_rows) == 1

    skips = db_session.query(DuplicateSkip).filter(DuplicateSkip.native_id == "LDG-3001").all()
    assert len(skips) == 1
    assert skips[0].original_raw_id == ldg3001_rows[0].raw_id


def test_bad_ledger_rows_flagged_not_dropped(db_session):
    run_ingestion(session=db_session)
    db_session.commit()

    def flagged(native_id):
        rec = (
            db_session.query(RawRecord)
            .filter(RawRecord.native_id == native_id, RawRecord.source == "ledger")
            .first()
        )
        assert rec is not None, f"{native_id} was dropped, not flagged"
        return rec

    missing_currency = flagged("LDG-4001")
    assert missing_currency.validation_status == "flagged"
    assert "currency" in missing_currency.flag_reason

    truncated_ts = flagged("LDG-4002")
    assert truncated_ts.validation_status == "flagged"
    assert "timestamp" in truncated_ts.flag_reason

    negative_amount = flagged("LDG-4003")
    assert negative_amount.validation_status == "flagged"
    assert "negative amount" in negative_amount.flag_reason


def test_valid_rows_not_flagged(db_session):
    run_ingestion(session=db_session)
    db_session.commit()
    clean = (
        db_session.query(RawRecord)
        .filter(RawRecord.native_id == "LDG-1001")
        .first()
    )
    assert clean.validation_status == "valid"
    assert clean.flag_reason is None


def test_raw_payload_untouched(db_session):
    run_ingestion(session=db_session)
    db_session.commit()
    rec = (
        db_session.query(RawRecord)
        .filter(RawRecord.native_id == "LDG-1001")
        .first()
    )
    assert rec.raw_payload["amount"] == "4999.00"
    assert rec.raw_payload["counterparty"] == "Razorpay"
