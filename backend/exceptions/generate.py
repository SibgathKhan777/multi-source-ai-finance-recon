"""Phase 5 — exception generation.

Walks every currently-unresolved match group (the *current* group each
canonical record actually points to -- not stale, superseded rows) and
classifies it into an exception: conflicting, unmatched, partial, orphan,
or disputed. Each exception is then run through the rules table (Phase 5's
finance_ops-editable data, see rules.py) to decide auto-acknowledgment and
routing.
"""
import hashlib
from datetime import datetime, timezone

from database import get_session
from models import CanonicalRecord, MatchGroup, Exception_
from exceptions.rules import seed_rules, evaluate_rules

FEE_MATCH_TOLERANCE = 0.01
SMALL_DIFF_CEILING = 5.00  # absolute cap for "clearly a rounding/small variance", not a real mismatch
CORRELATION_DATE_WINDOW_DAYS = 3


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _fingerprint(canonical_ids, exc_type, field=None):
    payload = "|".join(sorted(canonical_ids)) + f"|{exc_type}|{field or ''}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _current_groups(session):
    """One entry per canonical record's *current* group id, deduplicated,
    with unmatched/partial/disputed status only (matched groups are done).
    """
    group_ids = sorted({
        row[0] for row in session.query(CanonicalRecord.match_group_id).all() if row[0]
    })
    out = {}
    for gid in group_ids:
        group = (
            session.query(MatchGroup)
            .filter(MatchGroup.match_group_id == gid)
            .order_by(MatchGroup.version.desc())
            .first()
        )
        if group and group.status != "matched":
            out[gid] = group
    return out


def _members(session, group):
    return [session.get(CanonicalRecord, m.canonical_id) for m in group.members]


def _explain_via_fee(anchor_leg, candidate_amount):
    """Story 20's signature: the missing/odd leg is short by exactly the
    fee on the matched PSP leg -- a fee formula bug, not a real mismatch.
    """
    if anchor_leg.fee is None:
        return None
    diff = abs(anchor_leg.amount - candidate_amount) if anchor_leg.amount is not None else None
    if diff is not None and abs(diff - anchor_leg.fee) <= FEE_MATCH_TOLERANCE:
        return diff
    return None


def _create_exception(session, canonical_ids, exc_type, detail, context, story_id=None):
    fp = _fingerprint(canonical_ids, exc_type, context.get("field"))
    existing = session.query(Exception_).filter(Exception_.fingerprint == fp).first()
    if existing:
        return existing, False

    should_ack, ack_rule, owner, route_rule = evaluate_rules(session, context)
    exc_id = f"EXC-{session.query(Exception_).count() + 1:05d}"
    # guard against id collisions if exceptions were deleted/regenerated
    while session.get(Exception_, exc_id):
        exc_id = f"EXC-{int(exc_id.split('-')[1]) + 1:05d}"

    exc = Exception_(
        exception_id=exc_id,
        fingerprint=fp,
        type=exc_type,
        detail=detail,
        status="acknowledged" if should_ack else "new",
        suggested_owner=owner,
        canonical_ids=canonical_ids,
        story_id=story_id,
        created_at=_now_iso(),
        acknowledged_at=_now_iso() if should_ack else None,
        acknowledged_by=ack_rule if should_ack else None,
    )
    session.add(exc)
    session.flush()  # so the next _create_exception's count()-based id sees this row
    return exc, True


def _try_absorb_conflicting_pair(session, group, members, absorbed_group_ids):
    """A 'partial' group whose nearest_candidate is explained by a fee, or
    is a small enough diff to clearly be the same transaction, becomes one
    'conflicting' exception spanning both groups instead of a conflicting
    exception plus a spurious orphan for the other side.
    """
    nearest = (group.detail or {}).get("nearest_candidate")
    if not nearest or nearest.get("diff") is None:
        return False

    anchor = next((m for m in members if m.source in ("ledger", "psp")), members[0])
    diff = nearest["diff"]
    field = None

    psp_leg = next((m for m in members if m.source == "psp"), None)
    fee_diff = _explain_via_fee(psp_leg, nearest["amount"]) if psp_leg else None

    if fee_diff is not None:
        field = "fee"
    elif diff <= SMALL_DIFF_CEILING:
        field = "amount"
    else:
        return False

    other_record = session.get(CanonicalRecord, nearest["native_id"])
    other_group_id = other_record.match_group_id if other_record else None
    all_ids = [m.canonical_id for m in members] + ([other_record.canonical_id] if other_record else [])

    detail = (
        f"{group.detail.get('missing_source')} leg present but amount differs by {diff:.2f} "
        f"from {anchor.native_id} ({nearest['raw_native_id']}: {nearest['amount']})"
    )
    if field == "fee":
        detail += f" -- matches the PSP fee ({psp_leg.fee}) exactly: looks like a fee formula bug"

    _create_exception(
        session, all_ids, "conflicting", detail,
        context={"type": "conflicting", "field": field, "amount_diff": round(diff, 2)},
    )
    if other_group_id:
        absorbed_group_ids.add(other_group_id)
    return True


def _try_correlate_bare_ledger_singleton(session, ledger_record, current_groups, absorbed_group_ids):
    """A lone unmatched ledger record (e.g. a negative-amount data-entry
    error) whose amount is too far off to have registered as anyone's
    'nearest candidate' at match time -- correlate it against any partial
    {psp,bank} pair for the same counterparty around the same date.
    """
    for gid, group in current_groups.items():
        if gid in absorbed_group_ids or group.status != "partial":
            continue
        if (group.detail or {}).get("missing_source") != "ledger":
            continue
        members = _members(session, group)
        rep = members[0]
        if rep.counterparty_id != ledger_record.counterparty_id:
            continue
        if rep.ts_utc is None or ledger_record.ts_utc is None:
            continue
        if abs((rep.ts_utc.date() - ledger_record.ts_utc.date()).days) > CORRELATION_DATE_WINDOW_DAYS:
            continue

        if ledger_record.amount is None or rep.amount is None:
            continue
        magnitude_diff = abs(abs(ledger_record.amount) - rep.amount)
        raw_diff = abs(ledger_record.amount - rep.amount)  # the actual conflict severity (sign-sensitive)
        if magnitude_diff > SMALL_DIFF_CEILING:
            continue  # not the same transaction, just coincidentally nearby

        all_ids = [ledger_record.canonical_id] + [m.canonical_id for m in members]
        detail = (
            f"ledger amount {ledger_record.amount} conflicts with the matched PSP+bank pair "
            f"({rep.amount}) for the same counterparty/date"
        )
        _create_exception(
            session, all_ids, "conflicting", detail,
            context={"type": "conflicting", "field": "amount", "amount_diff": round(raw_diff, 2)},
        )
        absorbed_group_ids.add(gid)
        return True
    return False


def _classify_remaining(session, gid, group, members):
    if group.status == "disputed":
        native_ids = ", ".join(f"{m.source}:{m.native_id}" for m in members)
        _create_exception(
            session, [m.canonical_id for m in members], "disputed",
            f"chargeback/dispute detected across {native_ids}; amounts differ by sign (reversal), not a plain mismatch",
            context={"type": "disputed"},
        )
        return

    if group.status == "partial":
        missing = (group.detail or {}).get("missing_source", "unknown")
        present = ", ".join(f"{m.source}:{m.native_id}" for m in members)
        _create_exception(
            session, [m.canonical_id for m in members], "partial",
            f"{present} matched, but no corresponding {missing} record found yet",
            context={"type": "partial", "missing_source": missing},
        )
        return

    if group.status == "unmatched" and len(members) == 1:
        record = members[0]
        _create_exception(
            session, [record.canonical_id], "orphan",
            f"{record.source}:{record.native_id} (amount {record.amount}) has no counterpart in any other source",
            context={"type": "orphan", "source": record.source},
        )
        return

    # fallback: anything unclassified above (e.g. a still-unresolved held
    # revision/refund leg) still gets surfaced rather than silently dropped
    _create_exception(
        session, [m.canonical_id for m in members], "unmatched",
        f"unresolved group ({group.method or 'no method'}): " + ", ".join(f"{m.source}:{m.native_id}" for m in members),
        context={"type": "unmatched"},
    )


def generate_exceptions(session=None):
    own_session = session is None
    session = session or get_session()
    seed_rules(session=session)

    current_groups = _current_groups(session)
    absorbed_group_ids = set()

    # Pass 1: absorb partial groups whose nearest_candidate genuinely
    # explains a conflict (fee bug, small rounding diff).
    for gid, group in list(current_groups.items()):
        if group.status != "partial":
            continue
        members = _members(session, group)
        if _try_absorb_conflicting_pair(session, group, members, absorbed_group_ids):
            absorbed_group_ids.add(gid)

    # Pass 2: correlate bare ledger singletons (e.g. negative-amount data
    # errors) against a partial {psp,bank} pair for the same transaction.
    for gid, group in list(current_groups.items()):
        if gid in absorbed_group_ids or group.status != "unmatched":
            continue
        members = _members(session, group)
        if len(members) == 1 and members[0].source == "ledger":
            if _try_correlate_bare_ledger_singleton(session, members[0], current_groups, absorbed_group_ids):
                absorbed_group_ids.add(gid)

    # Pass 3: everything left gets classified on its own.
    created = 0
    for gid, group in current_groups.items():
        if gid in absorbed_group_ids:
            continue
        members = _members(session, group)
        before = session.query(Exception_).count()
        _classify_remaining(session, gid, group, members)
        if session.query(Exception_).count() > before:
            created += 1

    if own_session:
        session.commit()

    return {"exceptions_created": created, "total_exceptions": session.query(Exception_).count()}


def acknowledge_exception(session, exception_id: str, acknowledged_by: str = "manual"):
    exc = session.get(Exception_, exception_id)
    if exc is None:
        return None
    exc.status = "acknowledged"
    exc.acknowledged_at = _now_iso()
    exc.acknowledged_by = acknowledged_by
    return exc
