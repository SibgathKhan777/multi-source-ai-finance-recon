from ingestion.pipeline import run_ingestion
from normalization.normalize import run_normalization
from matching.engine import run_matching
from agent.reasoning import run_agent
from models import CanonicalRecord, MatchGroup


def _setup(session):
    run_ingestion(session=session)
    session.commit()
    run_normalization(session=session)
    session.commit()
    run_matching(session=session)
    session.commit()
    result = run_agent(session=session)
    session.commit()
    return result


def _status_for(session, native_id, source="ledger"):
    rec = (
        session.query(CanonicalRecord)
        .filter(CanonicalRecord.native_id == native_id, CanonicalRecord.source == source)
        .order_by(CanonicalRecord.canonical_id.desc())
        .first()
    )
    group = (
        session.query(MatchGroup)
        .filter(MatchGroup.match_group_id == rec.match_group_id)
        .order_by(MatchGroup.version.desc())
        .first()
    )
    return group.status


def test_story8_missing_currency_resolved(db_session):
    _setup(db_session)
    assert _status_for(db_session, "LDG-4001") == "matched"
    rec = (
        db_session.query(CanonicalRecord)
        .filter(CanonicalRecord.native_id == "LDG-4001")
        .first()
    )
    assert rec.currency == "INR"
    assert rec.currency_inferred is True


def test_story9_date_only_resolved(db_session):
    _setup(db_session)
    assert _status_for(db_session, "LDG-4002") == "matched"


def test_story16_timestamp_drift_resolved(db_session):
    _setup(db_session)
    assert _status_for(db_session, "LDG-9001") == "matched"


def test_story17_crosswalk_gap_resolved(db_session):
    _setup(db_session)
    assert _status_for(db_session, "LDG-9002") == "matched"
    rec = (
        db_session.query(CanonicalRecord)
        .filter(CanonicalRecord.native_id == "LDG-9002")
        .first()
    )
    assert rec.counterparty_id == "CP-RAZORPAY"


def test_story12_refund_net_settlement_resolved(db_session):
    _setup(db_session)
    revised = (
        db_session.query(CanonicalRecord)
        .filter(CanonicalRecord.native_id == "LDG-6001")
        .order_by(CanonicalRecord.canonical_id)
        .all()
    )
    assert len(revised) == 2
    group = (
        db_session.query(MatchGroup)
        .filter(MatchGroup.match_group_id == revised[1].match_group_id)
        .first()
    )
    assert group.status == "matched"
    assert group.detail.get("net_amount") == 5400.00


def test_story10_negative_amount_not_resolved(db_session):
    _setup(db_session)
    status = _status_for(db_session, "LDG-4003")
    assert status != "matched", "agent must not force-match a genuine data-entry error"


def test_story10_agent_decision_logged_as_declined(db_session):
    _setup(db_session)
    from models import AgentDecision

    decisions = db_session.query(AgentDecision).filter(AgentDecision.resolved.is_(False)).all()
    reasons = [d.reason for d in decisions]
    assert any("negative" in r.lower() for r in reasons)


def test_story11_and_story20_left_for_phase5(db_session):
    _setup(db_session)
    assert _status_for(db_session, "LDG-5001") != "matched"  # story 11: rounding, Phase 5's job
    assert _status_for(db_session, "LDG-9701") != "matched"  # story 20: fee conflict, Phase 5's job


def test_story13_late_arrival_still_unresolved_pending_phase6(db_session):
    _setup(db_session)
    assert _status_for(db_session, "LDG-7001") != "matched"


def test_resolved_and_declined_counts(db_session):
    result = _setup(db_session)
    assert result["resolved"] == 5
    assert result["declined"] == 5
