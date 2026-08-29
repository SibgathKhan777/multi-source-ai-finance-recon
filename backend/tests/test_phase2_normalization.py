from ingestion.pipeline import run_ingestion
from normalization.normalize import run_normalization
from models import CanonicalRecord


def _canon(session, native_id, source=None):
    q = session.query(CanonicalRecord).filter(CanonicalRecord.native_id == native_id)
    if source:
        q = q.filter(CanonicalRecord.source == source)
    return q.first()


def _setup(session):
    run_ingestion(session=session)
    session.commit()
    run_normalization(session=session)
    session.commit()


def test_story19_timezones_normalize_to_same_instant(db_session):
    _setup(db_session)
    ledger = _canon(db_session, "LDG-9601", "ledger")
    psp = _canon(db_session, "pay_J001", "psp")
    assert ledger.ts_utc is not None
    assert psp.ts_utc is not None
    assert ledger.ts_utc == psp.ts_utc, (
        f"story 19 timezone normalization failed: {ledger.ts_utc} != {psp.ts_utc}"
    )


def test_crosswalk_resolves_known_alias(db_session):
    _setup(db_session)
    rec = _canon(db_session, "LDG-1005", "ledger")
    assert rec.counterparty_id == "CP-RAZORPAY"


def test_crosswalk_leaves_near_miss_unresolved(db_session):
    _setup(db_session)
    rec = _canon(db_session, "LDG-9002", "ledger")
    assert rec.counterparty_raw == "Razorpay Technologies"
    assert rec.counterparty_id is None, "story 17 gap must stay open for the agent"


def test_bank_narration_resolves_via_substring(db_session):
    _setup(db_session)
    rec = _canon(db_session, "NEFT-1001", "bank")
    assert rec.counterparty_id == "CP-RAZORPAY"
    cashfree = _canon(db_session, "NEFT-1003", "bank")
    assert cashfree.counterparty_id == "CP-CASHFREE"


def test_batch_id_extracted_from_ledger_notes(db_session):
    _setup(db_session)
    for native_id in ["LDG-2001", "LDG-2002", "LDG-2003", "LDG-2004", "LDG-2005"]:
        rec = _canon(db_session, native_id, "ledger")
        assert rec.settlement_batch_id == "BATCH-4471"


def test_missing_currency_stays_null_for_agent(db_session):
    _setup(db_session)
    rec = _canon(db_session, "LDG-4001", "ledger")
    assert rec.currency is None
    assert rec.currency_inferred is False


def test_chargeback_detected_across_sources(db_session):
    _setup(db_session)
    ledger = _canon(db_session, "LDG-9501", "ledger")
    psp = _canon(db_session, "pay_I001", "psp")
    bank = _canon(db_session, "NEFT-9501", "bank")
    assert ledger.event_type == "chargeback"
    assert psp.event_type == "chargeback"
    assert bank.event_type == "chargeback"
    assert ledger.state == "disputed" and psp.state == "disputed" and bank.state == "disputed"


def test_refund_event_detected(db_session):
    _setup(db_session)
    psp_refund = _canon(db_session, "rfnd_F001", "psp")
    bank_refund = _canon(db_session, "NEFT-6002", "bank")
    assert psp_refund.event_type == "refund"
    assert bank_refund.event_type == "refund"


def test_negative_ledger_amount_still_canonicalized(db_session):
    _setup(db_session)
    rec = _canon(db_session, "LDG-4003", "ledger")
    assert rec is not None
    assert rec.amount == -750.00


def test_all_valid_and_flagged_rows_get_canonical_records(db_session):
    _setup(db_session)
    from models import RawRecord

    raw_count = db_session.query(RawRecord).count()
    canon_count = db_session.query(CanonicalRecord).count()
    assert raw_count == canon_count == 67
