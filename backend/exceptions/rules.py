"""Phase 5 — rules table. Data, not code: finance_ops can add/edit a row
here (via the API) without anyone touching the exception-generation code.
"""
from datetime import datetime, timezone

from database import get_session
from models import Rule

SEED_RULES = [
    ("RULE-001", {"field": "amount_diff", "operator": "<", "value": 1.00}, "auto_acknowledge", None),
    ("RULE-002", {"type": "orphan", "source": "ledger"}, "route", "finance_ops"),
    ("RULE-003", {"type": "conflicting", "field": "fee"}, "route", "engineering"),
    ("RULE-004", {"type": "orphan", "source": "bank"}, "route", "engineering"),
    ("RULE-005", {"type": "disputed"}, "route", "finance_ops"),
]

DEFAULT_OWNER_BY_TYPE = {
    "conflicting": "engineering",
    "partial": "finance_ops",
    "orphan": "engineering",
    "unmatched": "engineering",
    "disputed": "finance_ops",
}

_OPERATORS = {
    "<": lambda a, b: a is not None and a < b,
    "<=": lambda a, b: a is not None and a <= b,
    ">": lambda a, b: a is not None and a > b,
    ">=": lambda a, b: a is not None and a >= b,
    "==": lambda a, b: a == b,
}


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def seed_rules(session=None):
    own_session = session is None
    session = session or get_session()
    if session.query(Rule).count() == 0:
        for rule_id, condition, action, owner in SEED_RULES:
            session.add(Rule(rule_id=rule_id, condition=condition, action=action, owner=owner, active=True, created_at=_now_iso()))
        if own_session:
            session.commit()
        else:
            session.flush()


def _condition_matches(condition: dict, context: dict) -> bool:
    if "operator" in condition:
        field_val = context.get(condition["field"])
        op = _OPERATORS.get(condition["operator"])
        return bool(op and op(field_val, condition["value"]))
    # exact-match filter: every key in condition must equal the context value
    return all(context.get(k) == v for k, v in condition.items())


def evaluate_rules(session, context: dict):
    """Returns (should_auto_acknowledge, matched_ack_rule_id, suggested_owner, matched_route_rule_id)."""
    rules = session.query(Rule).filter(Rule.active.is_(True)).order_by(Rule.rule_id).all()

    ack_rule = None
    for rule in rules:
        if rule.action == "auto_acknowledge" and _condition_matches(rule.condition, context):
            ack_rule = rule.rule_id
            break

    owner, route_rule = None, None
    for rule in rules:
        if rule.action == "route" and _condition_matches(rule.condition, context):
            owner, route_rule = rule.owner, rule.rule_id
            break

    if owner is None:
        owner = DEFAULT_OWNER_BY_TYPE.get(context.get("type"), "finance_ops")

    return ack_rule is not None, ack_rule, owner, route_rule
