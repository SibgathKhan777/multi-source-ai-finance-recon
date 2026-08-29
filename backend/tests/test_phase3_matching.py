from ingestion.pipeline import run_ingestion
from normalization.normalize import run_normalization
from matching.engine import run_matching
from models import CanonicalRecord, MatchGroup, MatchGroupMember


def _setup(session):
    run_ingestion(session=session)
    session.commit()
    run_normalization(session=session)
    session.commit()
    run_matching(session=session)
    session.commit()


def _group_status_for(session, native_id, source):
    rec = (
        session.query(CanonicalRecord)
        .filter(CanonicalRecord.native_id == native_id, CanonicalRecord.source == source)
        .first()
    )
    assert rec is not None, f"{native_id} missing from canonical records"
    if rec.match_group_id is None:
        return None
    group = (
        session.query(MatchGroup)
        .filter(MatchGroup.match_group_id == rec.match_group_id)
        .order_by(MatchGroup.version.desc())
        .first()
    )
    return group.status if group else None


def test_stories_1_through_5_matched(db_session):
    _setup(db_session)
    for native_id in ["LDG-1001", "LDG-1002", "LDG-1003", "LDG-1004", "LDG-1005"]:
        status = _group_status_for(db_session, native_id, "ledger")
        assert status == "matched", f"{native_id} expected matched, got {status}"


def test_story6_batch_nets_to_computed_total_not_hardcoded(db_session):
    _setup(db_session)
    legs = (
        db_session.query(CanonicalRecord)
        .filter(CanonicalRecord.settlement_batch_id == "BATCH-4471", CanonicalRecord.source == "psp")
        .all()
    )
    assert len(legs) == 5
    computed_net = round(sum((l.amount or 0) - (l.fee or 0) for l in legs), 2)
    assert computed_net == 5120.50  # sanity check on the fixture, not the code path

    status = _group_status_for(db_session, "LDG-2001", "ledger")
    assert status == "matched"

    group = db_session.query(MatchGroup).filter(
        MatchGroup.match_group_id == db_session.query(CanonicalRecord.match_group_id)
        .filter(CanonicalRecord.native_id == "LDG-2001").scalar()
    ).first()
    assert group.detail["net_amount"] == computed_net
    assert group.method == "net_settlement_batch"

    # all 5 ledger legs + 5 psp legs + 1 bank row should be members
    members = db_session.query(MatchGroupMember).filter(MatchGroupMember.match_group_row_id == group.id).all()
    assert len(members) == 11


def test_stories_needing_agent_not_matched_by_phase3(db_session):
    _setup(db_session)
    cases = [
        ("LDG-4001", "ledger"),  # story 8 missing currency
        ("LDG-4002", "ledger"),  # story 9 date-only ts
        ("LDG-5001", "ledger"),  # story 11 rounding diff
        ("LDG-9001", "ledger"),  # story 16 45-min drift
        ("LDG-9002", "ledger"),  # story 17 crosswalk gap
    ]
    for native_id, source in cases:
        status = _group_status_for(db_session, native_id, source)
        assert status != "matched", f"{native_id} should NOT be matched yet, got {status}"


def test_story19_timezone_normalized_matches_cleanly(db_session):
    _setup(db_session)
    status = _group_status_for(db_session, "LDG-9601", "ledger")
    assert status == "matched"


def test_story18_chargeback_not_forced_matched_or_unmatched(db_session):
    _setup(db_session)
    status = _group_status_for(db_session, "LDG-9501", "ledger")
    assert status == "disputed"


def test_story14_orphan_ledger_stays_unmatched(db_session):
    _setup(db_session)
    status = _group_status_for(db_session, "LDG-8001", "ledger")
    assert status == "unmatched"


def test_story15_orphan_bank_stays_unmatched(db_session):
    _setup(db_session)
    status = _group_status_for(db_session, "NEFT-8001", "bank")
    assert status == "unmatched"


def test_story13_late_bank_leaves_ledger_psp_partial(db_session):
    _setup(db_session)
    status = _group_status_for(db_session, "LDG-7001", "ledger")
    assert status == "partial"


def test_story12_refund_legs_held_out_for_agent(db_session):
    _setup(db_session)
    # the ORIGINAL 6000 leg across all 3 sources should match cleanly
    orig_status = _group_status_for(db_session, "pay_F001", "psp")
    assert orig_status == "matched"

    # the revised ledger row (5400) and the refund legs should NOT be silently
    # matched or merged by the matching engine -- that's the agent's job
    revised = (
        db_session.query(CanonicalRecord)
        .filter(CanonicalRecord.native_id == "LDG-6001")
        .order_by(CanonicalRecord.canonical_id)
        .all()
    )
    assert len(revised) == 2
    assert revised[1].amount == 5400.00
    group = (
        db_session.query(MatchGroup)
        .filter(MatchGroup.match_group_id == revised[1].match_group_id)
        .first()
    )
    assert group.status == "unmatched"
    assert group.detail.get("hold_reason") == "ledger_revision"
