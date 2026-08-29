"""Phase 3 — matching engine.

Sequential passes, cheapest first. Each pass only touches canonical
records that are still unclaimed after the previous pass. Everything
still unclaimed at the end is left for Phase 4 (agent reasoning) or,
if the agent doesn't touch it, Phase 5 (exceptions).
"""
from collections import defaultdict
from datetime import datetime, timezone

from database import get_session
from models import CanonicalRecord, MatchGroup, MatchGroupMember
from config import TIMESTAMP_TOLERANCE_MINUTES, AMOUNT_TOLERANCE_ABS, AMOUNT_TOLERANCE_PCT


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _next_group_n(session) -> int:
    last = (
        session.query(MatchGroup.match_group_id)
        .order_by(MatchGroup.match_group_id.desc())
        .first()
    )
    return int(last[0].split("-")[1]) if last else 0


class MatchingContext:
    """Holds mutable pass state for a single run_matching() call."""

    def __init__(self, session):
        self.session = session
        self.group_n = _next_group_n(session)
        self.claimed_ids = set()

    def next_group_id(self) -> str:
        self.group_n += 1
        return f"MG-{self.group_n:05d}"

    def create_group(self, canonical_ids, status, method, detail=None, revision_reason=None,
                      previous_version_id=None, version=1):
        group_id = self.next_group_id() if previous_version_id is None else \
            self.session.get(MatchGroup, previous_version_id).match_group_id
        group = MatchGroup(
            match_group_id=group_id,
            version=version,
            status=status,
            method=method,
            revision_reason=revision_reason,
            previous_version_id=previous_version_id,
            detail=detail or {},
            created_at=_now_iso(),
        )
        self.session.add(group)
        self.session.flush()
        for cid in canonical_ids:
            self.session.add(MatchGroupMember(match_group_row_id=group.id, canonical_id=cid))
            self.claimed_ids.add(cid)
            rec = self.session.get(CanonicalRecord, cid)
            rec.match_group_id = group_id
        self.session.flush()
        return group


def _unclaimed(records, claimed):
    return [r for r in records if r.canonical_id not in claimed]


def _by_source(records):
    out = defaultdict(list)
    for r in records:
        out[r.source].append(r)
    return out


def _amounts_close(a, b, cap):
    if a is None or b is None:
        return False
    return abs(a - b) <= cap


def _ts_compatible(anchor, candidate, tol_minutes, allow_date_only=False):
    """Bank statements only ever carry a date (no intraday time) — that's
    a structural property of the source, not a data-quality flag, so bank
    legs always compare at day granularity. A non-bank record that's
    date-only (story 9) is a genuine anomaly and is NOT considered
    compatible here by default; it needs the agent's judgment call
    (agent callers pass allow_date_only=True), not a silent day-level pass.
    """
    a_ts, c_ts = anchor.ts_utc, candidate.ts_utc
    if a_ts is None or c_ts is None:
        return False
    a_date_only = anchor.ts_precision == "date_only" and anchor.source != "bank"
    c_date_only = candidate.ts_precision == "date_only" and candidate.source != "bank"
    if (a_date_only or c_date_only) and not allow_date_only:
        return False
    if anchor.source == "bank" or candidate.source == "bank" or a_date_only or c_date_only:
        return a_ts.date() == c_ts.date()
    return abs((a_ts - c_ts).total_seconds()) <= tol_minutes * 60


def field_match_relaxed(anchor, candidate, *, amount_cap, ts_tol_minutes,
                         ignore_currency=False, allow_date_only=False, ignore_counterparty=False):
    """Core 1:1 comparison, used strictly by passes 1/2 and with specific,
    named relaxations by the Phase 4 agent -- each relaxation loosens
    exactly one constraint and leaves the rest intact, so a resolution
    still has to earn every other field matching.
    """
    if not ignore_counterparty:
        if anchor.counterparty_id is None or candidate.counterparty_id is None:
            return False, None
        if anchor.counterparty_id != candidate.counterparty_id:
            return False, None
    # Bank statements carry no currency column at all -- that's a structural
    # gap, not a data-quality issue, so currency is only compared between
    # currency-bearing sources (ledger/psp). A ledger/psp side that's
    # missing currency (story 8) genuinely needs the agent.
    if not ignore_currency and anchor.source != "bank" and candidate.source != "bank":
        if anchor.currency is None or candidate.currency is None:
            return False, None
        if anchor.currency != candidate.currency:
            return False, None
    if not _ts_compatible(anchor, candidate, ts_tol_minutes, allow_date_only=allow_date_only):
        return False, None
    amount_diff = abs(anchor.amount - candidate.amount) if anchor.amount is not None and candidate.amount is not None else None
    if amount_diff is None or amount_diff > amount_cap:
        return False, None
    return True, amount_diff


def _find_best(anchor, pool, **kwargs):
    best, best_diff = None, None
    for cand in pool:
        ok, diff = field_match_relaxed(anchor, cand, **kwargs)
        if ok and (best is None or diff < best_diff):
            best, best_diff = cand, diff
    return best


def _run_1to1_pass(ctx, primary_pool, method_name, amount_cap, ts_tol_minutes):
    by_source = _by_source(_unclaimed(primary_pool, ctx.claimed_ids))
    ledgers = list(by_source.get("ledger", []))

    for anchor in ledgers:
        if anchor.canonical_id in ctx.claimed_ids:
            continue
        psp_pool = _unclaimed(by_source.get("psp", []), ctx.claimed_ids)
        bank_pool = _unclaimed(by_source.get("bank", []), ctx.claimed_ids)

        psp_match = _find_best(anchor, psp_pool, amount_cap=amount_cap, ts_tol_minutes=ts_tol_minutes)
        bank_match = _find_best(anchor, bank_pool, amount_cap=amount_cap, ts_tol_minutes=ts_tol_minutes)

        if psp_match and bank_match:
            ctx.create_group(
                [anchor.canonical_id, psp_match.canonical_id, bank_match.canonical_id],
                status="matched",
                method=method_name,
            )
        elif psp_match or bank_match:
            present = psp_match or bank_match
            missing_source = "bank" if bank_match is None else "psp"
            members = [anchor.canonical_id, present.canonical_id]
            nearest = None
            missing_pool = bank_pool if missing_source == "bank" else psp_pool
            near = _nearest_candidate(anchor, missing_pool)
            if near:
                nearest = {
                    "source": missing_source,
                    "native_id": near.canonical_id,
                    "raw_native_id": near.native_id,
                    "amount": near.amount,
                    "diff": abs(anchor.amount - near.amount) if anchor.amount is not None and near.amount is not None else None,
                }
            ctx.create_group(
                members,
                status="partial",
                method=method_name,
                detail={"missing_source": missing_source, "nearest_candidate": nearest},
            )

    # Second sweep: PSP legs with no ledger anchor at all (e.g. the ledger
    # side is missing or too broken to serve as an anchor) can still pair
    # up directly with a bank leg.
    for anchor in _unclaimed(by_source.get("psp", []), ctx.claimed_ids):
        bank_pool = _unclaimed(by_source.get("bank", []), ctx.claimed_ids)
        bank_match = _find_best(anchor, bank_pool, amount_cap=amount_cap, ts_tol_minutes=ts_tol_minutes)
        if bank_match:
            ctx.create_group(
                [anchor.canonical_id, bank_match.canonical_id],
                status="partial",
                method=method_name,
                detail={"missing_source": "ledger", "nearest_candidate": None},
            )


def _nearest_candidate(anchor, pool):
    """Same counterparty + closest date, ignoring amount/ts tolerance —
    used only to annotate *why* a partial match looks like a conflict
    (e.g. story 20's fee-shorted bank credit), not to auto-match it.
    """
    candidates = [c for c in pool if c.counterparty_id == anchor.counterparty_id]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda c: abs((c.ts_utc - anchor.ts_utc).total_seconds()) if c.ts_utc and anchor.ts_utc else float("inf"),
    )


def _run_pass1_exact(ctx, primary_pool):
    _run_1to1_pass(ctx, primary_pool, method_name="exact_match", amount_cap=0.001, ts_tol_minutes=1)


def _run_pass2_tolerance(ctx, primary_pool):
    _run_1to1_pass(
        ctx, primary_pool, method_name="field_match_tolerance",
        amount_cap=AMOUNT_TOLERANCE_ABS, ts_tol_minutes=TIMESTAMP_TOLERANCE_MINUTES,
    )


def _run_pass3_balance_sanity(ctx, all_records):
    ledger_sum = sum(r.amount for r in all_records if r.source == "ledger" and r.amount is not None and r.event_type == "payment")
    bank_credit_sum = sum(r.amount for r in all_records if r.source == "bank" and r.amount is not None and r.amount > 0)
    diff = abs(ledger_sum - bank_credit_sum)
    wildly_off = diff > 0.05 * max(ledger_sum, bank_credit_sum, 1)
    return {
        "ledger_sum": round(ledger_sum, 2),
        "bank_credit_sum": round(bank_credit_sum, 2),
        "diff": round(diff, 2),
        "flag": "wildly_off" if wildly_off else "ok",
    }


def _run_pass4_net_settlement(ctx, batch_pool, all_records):
    unclaimed = _unclaimed(batch_pool, ctx.claimed_ids)
    by_source = _by_source(unclaimed)
    psp_by_batch = defaultdict(list)
    for r in by_source.get("psp", []):
        if r.settlement_batch_id:
            psp_by_batch[r.settlement_batch_id].append(r)

    # Bank has no settlement_batch_id, so its side of the batch pool is
    # sourced from the full unclaimed record set, not just batch_pool.
    all_unclaimed_bank = [
        r for r in all_records if r.source == "bank" and r.canonical_id not in ctx.claimed_ids
    ]

    for batch_id, legs in psp_by_batch.items():
        if len(legs) < 2:
            continue  # not a real net-settlement batch, just one leg

        net = sum((leg.amount or 0) - (leg.fee or 0) for leg in legs)
        counterparty_id = legs[0].counterparty_id

        bank_pool = all_unclaimed_bank
        bank_match = None
        for b in bank_pool:
            if b.counterparty_id == counterparty_id and _amounts_close(b.amount, net, AMOUNT_TOLERANCE_ABS):
                bank_match = b
                break

        ledger_legs = [
            r for r in by_source.get("ledger", [])
            if r.settlement_batch_id == batch_id
        ]

        members = [leg.canonical_id for leg in legs] + [leg.canonical_id for leg in ledger_legs]
        detail = {"batch_id": batch_id, "net_amount": round(net, 2), "leg_count": len(legs)}

        if bank_match:
            members.append(bank_match.canonical_id)
            ctx.create_group(members, status="matched", method="net_settlement_batch", detail=detail)
        else:
            detail["missing_source"] = "bank"
            ctx.create_group(members, status="partial", method="net_settlement_batch", detail=detail)


def _run_pass5_nway_quorum(ctx, primary_pool, min_sources=2):
    """N-way quorum: match if records from at least `min_sources` distinct
    sources agree on counterparty + amount (tolerance) + time (tolerance),
    even without a full N-way set. Not exercised by this 3-source dataset
    (passes 1/2 already resolve every case that would qualify here), but
    implemented so a 4th+ source can plug in without changing passes 1-4.
    """
    unclaimed = _unclaimed(primary_pool, ctx.claimed_ids)
    groups = []
    used = set()
    for i, a in enumerate(unclaimed):
        if a.canonical_id in used:
            continue
        cluster = [a]
        for b in unclaimed[i + 1:]:
            if b.canonical_id in used or b.source == a.source:
                continue
            ok, _ = field_match_relaxed(
                a, b, amount_cap=AMOUNT_TOLERANCE_ABS, ts_tol_minutes=TIMESTAMP_TOLERANCE_MINUTES,
            )
            if ok:
                cluster.append(b)
        sources_covered = {r.source for r in cluster}
        if len(sources_covered) >= min_sources:
            for r in cluster:
                used.add(r.canonical_id)
            groups.append(cluster)

    for cluster in groups:
        ctx.create_group(
            [r.canonical_id for r in cluster], status="matched", method="nway_quorum",
            detail={"sources": sorted({r.source for r in cluster})},
        )
    return groups


def _handle_disputed(ctx, disputed_records):
    by_source = _by_source(disputed_records)
    ledgers = list(by_source.get("ledger", []))
    for anchor in ledgers:
        if anchor.canonical_id in ctx.claimed_ids:
            continue
        pool = [r for r in disputed_records if r.canonical_id not in ctx.claimed_ids and r is not anchor]
        matches = [anchor]
        for r in pool:
            if r.counterparty_id == anchor.counterparty_id and abs(abs(r.amount) - abs(anchor.amount)) <= AMOUNT_TOLERANCE_ABS:
                matches.append(r)
        ctx.create_group(
            [m.canonical_id for m in matches], status="disputed", method="chargeback_detected",
            detail={"note": "amount sign differs by design (reversal); routed as a dispute, not matched/unmatched"},
        )
    # any leftover disputed records with no ledger anchor become their own singleton disputed group
    leftover = [r for r in disputed_records if r.canonical_id not in ctx.claimed_ids]
    for r in leftover:
        ctx.create_group([r.canonical_id], status="disputed", method="chargeback_detected")


def run_matching(session=None):
    own_session = session is None
    session = session or get_session()
    ctx = MatchingContext(session)

    all_records = (
        session.query(CanonicalRecord)
        .filter(CanonicalRecord.match_group_id.is_(None))
        .all()
    )

    disputed = [r for r in all_records if r.event_type == "chargeback"]
    refund_events = [r for r in all_records if r.event_type == "refund"]

    # ledger revisions: same native_id, more than one canonical record ->
    # keep only the earliest in the primary pool, hold the rest for the agent.
    ledger_by_native = defaultdict(list)
    for r in all_records:
        if r.source == "ledger":
            ledger_by_native[r.native_id].append(r)
    revision_ids = set()
    for native_id, recs in ledger_by_native.items():
        if len(recs) > 1:
            recs_sorted = sorted(recs, key=lambda r: r.canonical_id)
            for r in recs_sorted[1:]:
                revision_ids.add(r.canonical_id)

    # Multi-leg settlement batches are inherently many:1 (several PSP/ledger
    # legs net to a single bank credit) -- a 1:1 pass would greedily grab
    # each leg's exact PSP counterpart and strand it as "partial" before
    # pass 4 ever sees it, so these batches skip passes 1/2 entirely.
    psp_by_batch_all = defaultdict(list)
    for r in all_records:
        if r.source == "psp" and r.settlement_batch_id and r.event_type == "payment":
            psp_by_batch_all[r.settlement_batch_id].append(r)
    multi_leg_batches = {bid for bid, legs in psp_by_batch_all.items() if len(legs) >= 2}
    batch_ids = {
        r.canonical_id for r in all_records
        if r.settlement_batch_id in multi_leg_batches
    }

    excluded_ids = (
        {r.canonical_id for r in disputed}
        | {r.canonical_id for r in refund_events}
        | revision_ids
        | batch_ids
    )
    primary_pool = [r for r in all_records if r.canonical_id not in excluded_ids]
    batch_pool = [r for r in all_records if r.canonical_id in batch_ids]

    _handle_disputed(ctx, disputed)

    _run_pass1_exact(ctx, primary_pool)
    _run_pass2_tolerance(ctx, primary_pool)
    balance_flag = _run_pass3_balance_sanity(ctx, all_records)
    _run_pass4_net_settlement(ctx, batch_pool, all_records)
    _run_pass5_nway_quorum(ctx, primary_pool)

    # everything still unclaimed (including held-out revisions/refunds) is
    # Phase 4's leftover pool. We still record singleton groups for plain
    # orphans now; the agent will re-open/merge groups as it resolves cases.
    leftover = [r for r in all_records if r.canonical_id not in ctx.claimed_ids]
    for r in leftover:
        tag = "ledger_revision" if r.canonical_id in revision_ids else (
            "refund_event" if r.canonical_id in refund_events else None
        )
        ctx.create_group(
            [r.canonical_id], status="unmatched", method=None,
            detail={"hold_reason": tag} if tag else None,
        )

    if own_session:
        session.commit()

    return {
        "matched_groups": session.query(MatchGroup).filter(MatchGroup.status == "matched").count(),
        "balance_sanity": balance_flag,
        "leftover_count": len(leftover),
    }
