"""Phase 2 — crosswalk table.

Maps every source-native counterparty string to one canonical entity id.
Deliberately does NOT include "Razorpay Technologies" — that near-miss
alias is left unresolved here on purpose; it's a crosswalk gap closed by
the agent in Phase 4 (story 17), not hardcoded away here.
"""
from datetime import datetime, timezone

from database import get_session
from models import Crosswalk

SEED_ENTRIES = [
    ("Razorpay", "CP-RAZORPAY"),
    ("Razorpay Pvt Ltd", "CP-RAZORPAY"),
    ("RZP_MERCHANT_881", "CP-RAZORPAY"),
    ("Cashfree", "CP-CASHFREE"),
    ("CASHFREE_MERCHANT_204", "CP-CASHFREE"),
]


def seed_crosswalk(session=None):
    own_session = session is None
    session = session or get_session()
    if session.query(Crosswalk).count() == 0:
        for native_name, counterparty_id in SEED_ENTRIES:
            session.add(Crosswalk(native_name=native_name, counterparty_id=counterparty_id))
        if own_session:
            session.commit()
        else:
            session.flush()


def _load_table(session):
    return {row.native_name.lower(): row.counterparty_id for row in session.query(Crosswalk).all()}


def resolve_counterparty(session, source: str, counterparty_raw: str):
    """Returns a counterparty_id or None if unresolved.

    ledger/psp: exact (case-insensitive) match against the crosswalk.
    bank: the narration is free text, so any crosswalk entry that appears
    as a substring resolves it (e.g. "RAZORPAY" inside "RAZORPAY SETTLEMENT REF9001").
    """
    if not counterparty_raw:
        return None
    table = _load_table(session)

    if source == "bank":
        narration = counterparty_raw.lower()
        for native_name_lower, counterparty_id in table.items():
            if native_name_lower in narration:
                return counterparty_id
        return None

    return table.get(counterparty_raw.strip().lower())
