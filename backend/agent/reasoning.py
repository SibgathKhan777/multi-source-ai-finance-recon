"""Phase 4 — agent reasoning layer (LangGraph).

Runs only on the leftover pool Phase 3 couldn't resolve deterministically.
For each near-miss ledger anchor, a small LangGraph state graph classifies
the kind of near-miss and routes to a dedicated resolver node. Every
resolver either produces a merged, matched group with a human-readable
reason, or explicitly declines and says why -- nothing is silently forced
into a match.

No external LLM call is made: with no model credentials configured for
this environment, "reasoning" here means an explicit, inspectable chain of
judgment calls encoded as graph nodes (see each resolver's docstring for
the judgment being made) rather than an opaque black box. The graph
structure is what LangGraph is used for; swapping a resolver's body for an
LLM call later is a local change, not a redesign.
"""
from datetime import datetime, timezone
from typing import Optional, TypedDict, List, Any

from langgraph.graph import StateGraph, END

from database import get_session
from models import CanonicalRecord, MatchGroup, MatchGroupMember, AgentDecision
from matching.engine import field_match_relaxed, MatchingContext
from normalization.crosswalk import SEED_ENTRIES
from config import AMOUNT_TOLERANCE_ABS, TIMESTAMP_TOLERANCE_MINUTES, DEFAULT_CURRENCY

DRIFT_TOLERANCE_MINUTES = 120  # generous outer bound for "reasonable settlement delay"


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


class AgentState(TypedDict, total=False):
    session: Any
    ctx: Any
    anchor: Any
    pool: List[Any]
    case: str
    resolved: bool
    reason: str
    action: Optional[str]
    members: List[str]


def _log_decision(state: AgentState):
    session = state["session"]
    session.add(
        AgentDecision(
            canonical_ids=state.get("members") or [state["anchor"].canonical_id],
            resolved=state["resolved"],
            reason=state["reason"],
            action=state.get("action"),
            created_at=_now_iso(),
        )
    )


def _existing_group_members(session, canonical_record):
    if not canonical_record.match_group_id:
        return []
    group = (
        session.query(MatchGroup)
        .filter(MatchGroup.match_group_id == canonical_record.match_group_id)
        .order_by(MatchGroup.version.desc())
        .first()
    )
    if not group:
        return []
    member_ids = [m.canonical_id for m in group.members]
    return [session.get(CanonicalRecord, cid) for cid in member_ids]


def _finalize_resolution(ctx, member_ids, reason, action, extra_detail=None):
    detail = {"agent_reason": reason, "agent_action": action}
    if extra_detail:
        detail.update(extra_detail)
    ctx.create_group(member_ids, status="matched", method="agent_resolved", detail=detail)


# ---- classification -------------------------------------------------

def classify(state: AgentState) -> AgentState:
    anchor = state["anchor"]
    pool = state["pool"]

    if anchor.amount is not None and anchor.amount < 0:
        state["case"] = "negative_amount"
        return state

    is_revision = any(
        r.source == "ledger" and r.native_id == anchor.native_id and r.canonical_id != anchor.canonical_id
        for r in pool
    ) or _has_matched_sibling(state["session"], anchor)
    if is_revision:
        state["case"] = "refund_lineage"
        return state

    if anchor.currency is None:
        state["case"] = "missing_currency"
        return state

    if anchor.ts_precision == "date_only":
        state["case"] = "date_only"
        return state

    if anchor.counterparty_id is None and anchor.counterparty_raw:
        state["case"] = "crosswalk_gap"
        return state

    state["case"] = "timestamp_drift"
    return state


def _has_matched_sibling(session, anchor):
    sibling = (
        session.query(CanonicalRecord)
        .filter(CanonicalRecord.native_id == anchor.native_id, CanonicalRecord.canonical_id != anchor.canonical_id)
        .first()
    )
    return sibling is not None


def _route(state: AgentState) -> str:
    return state["case"]


# ---- resolvers --------------------------------------------------------

def resolve_missing_currency(state: AgentState) -> AgentState:
    """Judgment call: this dataset only ever uses one currency (INR), so a
    blank currency field on an otherwise-matching record is a data-entry
    gap, not ambiguity -- infer it rather than stall the reconciliation.
    """
    session, ctx, anchor, pool = state["session"], state["ctx"], state["anchor"], state["pool"]
    existing = _existing_group_members(session, anchor)
    already = {r.canonical_id for r in existing}

    psp_candidates = [r for r in pool if r.source == "psp" and r.canonical_id not in already]
    best, best_diff = None, None
    for cand in psp_candidates:
        ok, diff = field_match_relaxed(
            anchor, cand, amount_cap=AMOUNT_TOLERANCE_ABS, ts_tol_minutes=TIMESTAMP_TOLERANCE_MINUTES,
            ignore_currency=True,
        )
        if ok and (best is None or diff < best_diff):
            best, best_diff = cand, diff

    if best is None:
        state["resolved"] = False
        state["reason"] = "missing currency, but no psp candidate matched on amount/time/counterparty"
        state["action"] = None
        return state

    anchor.currency = DEFAULT_CURRENCY
    anchor.currency_inferred = True
    members = [anchor.canonical_id, best.canonical_id] + [r.canonical_id for r in existing]
    reason = (
        f"currency field was blank; inferred {DEFAULT_CURRENCY} (the only currency present in this "
        f"dataset) and the record matches {best.native_id} cleanly on amount/time/counterparty"
    )
    _finalize_resolution(ctx, members, reason, "infer_currency")
    state["resolved"] = True
    state["reason"] = reason
    state["action"] = "infer_currency"
    state["members"] = members
    return state


def resolve_date_only(state: AgentState) -> AgentState:
    """Judgment call: a date-only timestamp isn't wrong, just imprecise --
    treat it as "matches somewhere in that day" rather than demanding a
    precision the source never recorded.
    """
    session, ctx, anchor, pool = state["session"], state["ctx"], state["anchor"], state["pool"]
    existing = _existing_group_members(session, anchor)
    already = {r.canonical_id for r in existing}

    candidates = [r for r in pool if r.source in ("psp", "bank") and r.canonical_id not in already]
    found = []
    for cand in candidates:
        ok, _ = field_match_relaxed(
            anchor, cand, amount_cap=AMOUNT_TOLERANCE_ABS, ts_tol_minutes=TIMESTAMP_TOLERANCE_MINUTES,
            allow_date_only=True,
        )
        if ok:
            found.append(cand)

    if not found:
        state["resolved"] = False
        state["reason"] = "timestamp truncated to date-only, but no candidate matched even at day granularity"
        state["action"] = None
        return state

    members = [anchor.canonical_id] + [r.canonical_id for r in found] + [r.canonical_id for r in existing]
    reason = (
        "timestamp was truncated to a bare date; treated as matching anywhere within that day, "
        "which lines up with " + ", ".join(sorted({r.native_id for r in found}))
    )
    _finalize_resolution(ctx, members, reason, "relax_date_precision")
    state["resolved"] = True
    state["reason"] = reason
    state["action"] = "relax_date_precision"
    state["members"] = members
    return state


def resolve_timestamp_drift(state: AgentState) -> AgentState:
    """Judgment call: a same-day settlement delay of a few dozen minutes
    beyond the strict tolerance is normal processing lag, not a different
    transaction -- but only when every other field lines up exactly.
    """
    session, ctx, anchor, pool = state["session"], state["ctx"], state["anchor"], state["pool"]
    existing = _existing_group_members(session, anchor)
    already = {r.canonical_id for r in existing}

    psp_pool = [r for r in pool if r.source == "psp" and r.canonical_id not in already]
    bank_pool = [r for r in pool if r.source == "bank" and r.canonical_id not in already]

    def best_of(candidates):
        best, best_diff = None, None
        for cand in candidates:
            ok, diff = field_match_relaxed(
                anchor, cand, amount_cap=AMOUNT_TOLERANCE_ABS, ts_tol_minutes=DRIFT_TOLERANCE_MINUTES,
            )
            if ok and (best is None or diff < best_diff):
                best, best_diff = cand, diff
        return best

    psp_match = best_of(psp_pool)
    bank_match = best_of(bank_pool)

    if psp_match is None and bank_match is None:
        state["resolved"] = False
        state["reason"] = "no confident resolution found for this candidate"
        state["action"] = None
        return state

    members = [anchor.canonical_id] + [r.canonical_id for r in existing]
    drift_minutes = None
    if psp_match:
        members.append(psp_match.canonical_id)
        drift_minutes = round(abs((anchor.ts_utc - psp_match.ts_utc).total_seconds()) / 60, 1)
    if bank_match:
        members.append(bank_match.canonical_id)

    reason = (
        f"timestamp drift of ~{drift_minutes} min beyond the standard tolerance, judged as the same "
        "transaction given amount, currency and counterparty all match exactly -- within reasonable "
        "settlement delay"
    )
    _finalize_resolution(ctx, members, reason, "relax_timestamp_tolerance", {"drift_minutes": drift_minutes})
    state["resolved"] = True
    state["reason"] = reason
    state["action"] = "relax_timestamp_tolerance"
    state["members"] = members
    return state


def resolve_crosswalk_gap(state: AgentState) -> AgentState:
    """Judgment call: a counterparty string not in the crosswalk table but
    that shares its recognizable core with a known alias (e.g. "Razorpay
    Technologies" contains "Razorpay") is very likely the same entity --
    but only act on it once amount/time/currency also line up.
    """
    session, ctx, anchor, pool = state["session"], state["ctx"], state["anchor"], state["pool"]
    raw = (anchor.counterparty_raw or "").lower()

    inferred_id = None
    for native_name, counterparty_id in SEED_ENTRIES:
        base = native_name.lower()
        if base in raw or raw in base:
            inferred_id = counterparty_id
            break

    if inferred_id is None:
        state["resolved"] = False
        state["reason"] = f"counterparty '{anchor.counterparty_raw}' has no recognizable match in the crosswalk"
        state["action"] = None
        return state

    existing = _existing_group_members(session, anchor)
    already = {r.canonical_id for r in existing}
    candidates = [r for r in pool if r.canonical_id not in already and r.counterparty_id == inferred_id]

    found = []
    for cand in candidates:
        ok, _ = field_match_relaxed(
            anchor, cand, amount_cap=AMOUNT_TOLERANCE_ABS, ts_tol_minutes=TIMESTAMP_TOLERANCE_MINUTES,
            ignore_counterparty=True,
        )
        if ok:
            found.append(cand)

    if not found:
        state["resolved"] = False
        state["reason"] = (
            f"'{anchor.counterparty_raw}' looks like a variant of a known counterparty, "
            "but no candidate matched on amount/time"
        )
        state["action"] = None
        return state

    anchor.counterparty_id = inferred_id
    members = [anchor.canonical_id] + [r.canonical_id for r in found] + [r.canonical_id for r in existing]
    reason = (
        f"'{anchor.counterparty_raw}' recognized as the same entity as an existing crosswalk alias "
        f"({inferred_id}); closes the crosswalk gap left open in Phase 2"
    )
    _finalize_resolution(ctx, members, reason, "crosswalk_resolve")
    state["resolved"] = True
    state["reason"] = reason
    state["action"] = "crosswalk_resolve"
    state["members"] = members
    return state


def resolve_refund_lineage(state: AgentState) -> AgentState:
    """Judgment call: a ledger amount revision that's explained by a
    matching PSP + bank refund event (same delta, same counterparty) is a
    net settlement, not a conflict -- link it to the original matched
    group instead of raising a mismatch.
    """
    session, ctx, anchor, pool = state["session"], state["ctx"], state["anchor"], state["pool"]

    original = (
        session.query(CanonicalRecord)
        .filter(CanonicalRecord.native_id == anchor.native_id, CanonicalRecord.canonical_id != anchor.canonical_id)
        .first()
    )
    if original is None or not original.match_group_id:
        state["resolved"] = False
        state["reason"] = "ledger revision found, but no already-matched original leg to anchor it to"
        state["action"] = None
        return state

    original_group = (
        session.query(MatchGroup)
        .filter(MatchGroup.match_group_id == original.match_group_id)
        .order_by(MatchGroup.version.desc())
        .first()
    )
    if original_group is None or original_group.status != "matched":
        state["resolved"] = False
        state["reason"] = "original leg exists but isn't cleanly matched, so the revision can't be net-explained yet"
        state["action"] = None
        return state

    delta = round(anchor.amount - original.amount, 2)
    original_members = [session.get(CanonicalRecord, m.canonical_id) for m in original_group.members]
    original_psp = next((r for r in original_members if r.source == "psp"), None)

    refund_candidates = [r for r in pool if r.event_type == "refund"]
    psp_refund = next(
        (r for r in refund_candidates if r.source == "psp" and original_psp and r.related_native_id == original_psp.native_id),
        None,
    )
    bank_refund = next(
        (
            r for r in refund_candidates
            if r.source == "bank" and r.counterparty_id == original.counterparty_id
            and abs(r.amount - delta) <= AMOUNT_TOLERANCE_ABS
        ),
        None,
    )

    if psp_refund is None or bank_refund is None or abs(psp_refund.amount - delta) > AMOUNT_TOLERANCE_ABS:
        state["resolved"] = False
        state["reason"] = (
            f"ledger amount changed by {delta}, but no matching PSP+bank refund event was found to explain it"
        )
        state["action"] = None
        return state

    members = [r.canonical_id for r in original_members] + [anchor.canonical_id, psp_refund.canonical_id, bank_refund.canonical_id]
    reason = (
        f"ledger amount change ({original.amount} -> {anchor.amount}) is explained by a separate refund "
        f"event of {delta}, confirmed by matching PSP ({psp_refund.native_id}) and bank ({bank_refund.native_id}) "
        "refund legs -- net matches, not a conflict"
    )
    _finalize_resolution(
        ctx, members, reason, "refund_net_settlement",
        {"original_amount": original.amount, "net_amount": anchor.amount, "refund_amount": delta, "lifecycle": "refunded"},
    )
    state["resolved"] = True
    state["reason"] = reason
    state["action"] = "refund_net_settlement"
    state["members"] = members
    return state


def reject_negative_amount(state: AgentState) -> AgentState:
    """Judgment call: a negative ledger amount for what should be a sale
    is a genuine data-entry error. The agent must not paper over it just
    because it could construct a plausible-sounding story -- it stays an
    exception for a human to fix.
    """
    anchor = state["anchor"]
    state["resolved"] = False
    state["reason"] = (
        f"ledger amount {anchor.amount} is negative for what should be a sale -- this is a genuine "
        "data-entry error, not a near-miss; declining to force a match"
    )
    state["action"] = "reject_negative_amount"
    return state


def unresolved_fallback(state: AgentState) -> AgentState:
    state.setdefault("resolved", False)
    state.setdefault("reason", "no applicable resolution")
    state.setdefault("action", None)
    return state


def _build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("classify", classify)
    graph.add_node("missing_currency", resolve_missing_currency)
    graph.add_node("date_only", resolve_date_only)
    graph.add_node("timestamp_drift", resolve_timestamp_drift)
    graph.add_node("crosswalk_gap", resolve_crosswalk_gap)
    graph.add_node("refund_lineage", resolve_refund_lineage)
    graph.add_node("negative_amount", reject_negative_amount)
    graph.add_node("log", _log_decision_node)

    graph.set_entry_point("classify")
    graph.add_conditional_edges(
        "classify",
        _route,
        {
            "missing_currency": "missing_currency",
            "date_only": "date_only",
            "timestamp_drift": "timestamp_drift",
            "crosswalk_gap": "crosswalk_gap",
            "refund_lineage": "refund_lineage",
            "negative_amount": "negative_amount",
        },
    )
    for node in ["missing_currency", "date_only", "timestamp_drift", "crosswalk_gap", "refund_lineage", "negative_amount"]:
        graph.add_edge(node, "log")
    graph.add_edge("log", END)
    return graph.compile()


def _log_decision_node(state: AgentState) -> AgentState:
    _log_decision(state)
    return state


_COMPILED_GRAPH = _build_graph()


def gather_leftover_ledger_records(session):
    leftover_group_ids = [
        row[0] for row in session.query(MatchGroup.match_group_id)
        .filter(MatchGroup.status.in_(["unmatched", "partial"]))
        .all()
    ]
    return (
        session.query(CanonicalRecord)
        .filter(CanonicalRecord.source == "ledger", CanonicalRecord.match_group_id.in_(leftover_group_ids))
        .order_by(CanonicalRecord.canonical_id)
        .all()
    )


def gather_leftover_pool(session):
    leftover_group_ids = [
        row[0] for row in session.query(MatchGroup.match_group_id)
        .filter(MatchGroup.status.in_(["unmatched", "partial"]))
        .all()
    ]
    return (
        session.query(CanonicalRecord)
        .filter(CanonicalRecord.match_group_id.in_(leftover_group_ids))
        .all()
    )


def run_agent(session=None):
    own_session = session is None
    session = session or get_session()
    ctx = MatchingContext(session)

    resolved_count = 0
    declined_count = 0
    decisions = []

    ledger_anchors = gather_leftover_ledger_records(session)
    for anchor in ledger_anchors:
        pool = gather_leftover_pool(session)
        initial_state: AgentState = {"session": session, "ctx": ctx, "anchor": anchor, "pool": pool}
        result = _COMPILED_GRAPH.invoke(initial_state)
        decisions.append({"native_id": anchor.native_id, "case": result["case"], "resolved": result["resolved"], "reason": result["reason"]})
        if result["resolved"]:
            resolved_count += 1
        else:
            declined_count += 1
        session.flush()

    if own_session:
        session.commit()

    return {"resolved": resolved_count, "declined": declined_count, "decisions": decisions}
