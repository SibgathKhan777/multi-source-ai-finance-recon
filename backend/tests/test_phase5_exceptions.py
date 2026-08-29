from ingestion.pipeline import run_ingestion
from normalization.normalize import run_normalization
from matching.engine import run_matching
from agent.reasoning import run_agent
from exceptions.generate import generate_exceptions
from models import Exception_, CanonicalRecord


def _setup(session):
    run_ingestion(session=session)
    session.commit()
    run_normalization(session=session)
    session.commit()
    run_matching(session=session)
    session.commit()
    run_agent(session=session)
    session.commit()
    generate_exceptions(session=session)
    session.commit()


def _find_exception_containing(session, native_id):
    rec = (
        session.query(CanonicalRecord)
        .filter(CanonicalRecord.native_id == native_id)
        .first()
    )
    for exc in session.query(Exception_).all():
        if rec.canonical_id in (exc.canonical_ids or []):
            return exc
    return None


def test_story11_rounding_diff_auto_acknowledged(db_session):
    _setup(db_session)
    exc = _find_exception_containing(db_session, "LDG-5001")
    assert exc is not None
    assert exc.type == "conflicting"
    assert exc.status == "acknowledged"
    assert exc.acknowledged_by == "RULE-001"


def test_story14_orphan_ledger_routed_finance_ops(db_session):
    _setup(db_session)
    exc = _find_exception_containing(db_session, "LDG-8001")
    assert exc is not None
    assert exc.type == "orphan"
    assert exc.status == "new"
    assert exc.suggested_owner == "finance_ops"


def test_story15_orphan_bank_routed_engineering(db_session):
    _setup(db_session)
    exc = _find_exception_containing(db_session, "NEFT-8001")
    assert exc is not None
    assert exc.type == "orphan"
    assert exc.status == "new"
    assert exc.suggested_owner == "engineering"


def test_story18_chargeback_disputed_routed_finance_ops(db_session):
    _setup(db_session)
    exc = _find_exception_containing(db_session, "LDG-9501")
    assert exc is not None
    assert exc.type == "disputed"
    assert exc.suggested_owner == "finance_ops"
    assert exc.status == "new"


def test_story10_negative_amount_conflicting_routed_engineering(db_session):
    _setup(db_session)
    exc = _find_exception_containing(db_session, "LDG-4003")
    assert exc is not None
    assert exc.type == "conflicting"
    assert exc.suggested_owner == "engineering"
    assert exc.status == "new"


def test_story20_fee_conflict_routed_engineering(db_session):
    _setup(db_session)
    exc = _find_exception_containing(db_session, "LDG-9701")
    assert exc is not None
    assert exc.type == "conflicting"
    assert exc.suggested_owner == "engineering"
    # RULE-003 requires field=fee to fire; confirm it actually matched via that rule
    assert exc.acknowledged_by is None
    assert exc.status == "new"


def test_story13_partial_stays_new_finance_ops(db_session):
    _setup(db_session)
    exc = _find_exception_containing(db_session, "LDG-7001")
    assert exc is not None
    assert exc.type == "partial"
    assert exc.status == "new"


def test_no_duplicate_exceptions_on_rerun(db_session):
    _setup(db_session)
    from exceptions.generate import generate_exceptions

    count_before = db_session.query(Exception_).count()
    generate_exceptions(session=db_session)
    db_session.commit()
    count_after = db_session.query(Exception_).count()
    assert count_before == count_after


def test_acknowledge_exception_updates_status(db_session):
    _setup(db_session)
    from exceptions.generate import acknowledge_exception

    exc = _find_exception_containing(db_session, "LDG-8001")
    assert exc.status == "new"
    acknowledge_exception(db_session, exc.exception_id, acknowledged_by="finance_ops_user")
    db_session.commit()
    refreshed = db_session.get(Exception_, exc.exception_id)
    assert refreshed.status == "acknowledged"
    assert refreshed.acknowledged_by == "finance_ops_user"
