"""Phase 6 — late-arrival / look-back window handling.

A record that shows up after its match group's run has already closed
doesn't get silently folded into whatever batch runs next -- it's
recognized as a revision of a SPECIFIC prior match group, which gets a
new version (old version preserved, never overwritten) rather than a
fresh, disconnected match.
"""
from datetime import datetime, timezone

from database import get_session
from models import CanonicalRecord, MatchGroup, Exception_
from normalization.normalize import run_normalization
from matching.engine import MatchingContext
from config import LOOK_BACK_DAYS, AMOUNT_TOLERANCE_ABS


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _current_open_groups(session):
    group_ids = sorted({
        row[0] for row in session.query(CanonicalRecord.match_group_id).all() if row[0]
    })
    out = []
    for gid in group_ids:
        group = (
            session.query(MatchGroup)
            .filter(MatchGroup.match_group_id == gid)
            .order_by(MatchGroup.version.desc())
            .first()
        )
        if group and group.status in ("unmatched", "partial") and group.closed_at is None:
            out.append(group)
    return out


def _find_affected_group(session, new_record, look_back_days):
    """Locates the specific match group a late-arriving record revises:
    same counterparty, missing exactly this record's source, transaction
    date within the look-back window of the original group's date.
    """
    for group in _current_open_groups(session):
        detail = group.detail or {}
        if detail.get("missing_source") != new_record.source:
            continue
        members = [session.get(CanonicalRecord, m.canonical_id) for m in group.members]
        rep = members[0]
        if rep.counterparty_id != new_record.counterparty_id:
            continue
        if rep.ts_utc is None or new_record.ts_utc is None:
            continue
        gap_days = (new_record.ts_utc.date() - rep.ts_utc.date()).days
        # a late arrival is by definition NOT on the original transaction
        # date -- that's what makes it late -- so this checks amount +
        # counterparty only, with the date gap itself bounded by the
        # look-back window instead of the usual same-day/tolerance rule.
        if gap_days < 0 or gap_days > look_back_days:
            continue
        if rep.amount is None or new_record.amount is None:
            continue
        if abs(rep.amount - new_record.amount) > AMOUNT_TOLERANCE_ABS:
            continue
        return group, members
    return None, None


def _acknowledge_superseded_exceptions(session, match_group_id, reason):
    exceptions = (
        session.query(Exception_)
        .filter(Exception_.status == "new")
        .all()
    )
    for exc in exceptions:
        # an exception references canonical ids from the OLD group's members;
        # if any of those ids belonged to the group we just superseded, close it
        rec_ids = exc.canonical_ids or []
        recs = [session.get(CanonicalRecord, cid) for cid in rec_ids]
        if any(r and r.match_group_id == match_group_id for r in recs):
            exc.status = "acknowledged"
            exc.acknowledged_at = _now_iso()
            exc.acknowledged_by = "system:late_arrival_reprocessing"


def _unclaimed_singleton_records(session):
    """Records sitting alone in a status='unmatched' group -- these are
    candidates for late-arrival correlation regardless of when they were
    ingested, not just ones normalized in this exact call.
    """
    out = []
    for group in _current_open_groups(session):
        if group.status == "unmatched" and len(group.members) == 1:
            out.append(session.get(CanonicalRecord, group.members[0].canonical_id))
    return out


def process_late_arrivals(session=None, look_back_days=None, new_raw_ids=None):
    """Normalizes any not-yet-normalized raw records, then checks every
    candidate record (freshly normalized, or already sitting unclaimed in a
    singleton group from an earlier run) against every open partial/unmatched
    group within the look-back window. Returns a summary of revisions made.
    """
    own_session = session is None
    session = session or get_session()
    look_back_days = look_back_days if look_back_days is not None else LOOK_BACK_DAYS

    norm_result = run_normalization(session=session)
    session.flush()  # run_normalization doesn't commit when a session is passed in
    new_canonical_ids = norm_result["canonical_ids"]

    if new_raw_ids is not None:
        wanted_raw_ids = set(new_raw_ids)
        new_records = [
            r for r in session.query(CanonicalRecord).filter(CanonicalRecord.canonical_id.in_(new_canonical_ids)).all()
            if r.raw_id in wanted_raw_ids
        ]
    else:
        fresh = session.query(CanonicalRecord).filter(CanonicalRecord.canonical_id.in_(new_canonical_ids)).all()
        seen = {r.canonical_id for r in fresh}
        candidates = fresh + [r for r in _unclaimed_singleton_records(session) if r.canonical_id not in seen]
        new_records = candidates

    ctx = MatchingContext(session)
    revisions = []

    for new_record in new_records:
        group, members = _find_affected_group(session, new_record, look_back_days)
        if group is None:
            continue

        group.closed_at = _now_iso()
        member_ids = [m.canonical_id for m in members]
        new_group = ctx.create_group(
            member_ids + [new_record.canonical_id],
            status="matched",
            method="late_arrival_reprocessing",
            detail={"revised_from_version": group.version},
            revision_reason=f"late {new_record.source} record arrived ({new_record.native_id})",
            previous_version_id=group.id,
            version=group.version + 1,
        )
        _acknowledge_superseded_exceptions(session, group.match_group_id, new_group.revision_reason)
        revisions.append({
            "match_group_id": new_group.match_group_id,
            "version": new_group.version,
            "revision_reason": new_group.revision_reason,
        })

    if own_session:
        session.commit()

    return {"revisions": revisions, "new_records_seen": len(new_records)}
