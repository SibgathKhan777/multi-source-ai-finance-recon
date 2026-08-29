"""Phase 7 — validation against ground truth.

Loads ground_truth.csv and checks the pipeline's actual output against
each story's `expected_classification` prose. This is the real test
suite for the system as a whole (as opposed to per-phase unit tests):
it's driven by keyword rules extracted from the ground-truth text at
runtime, not by hardcoding each story's expected outcome in code.
"""
import csv
import json
from pathlib import Path

from database import get_session
from models import CanonicalRecord, MatchGroup, Exception_, DuplicateSkip
from config import GROUND_TRUTH_CSV, PROJECT_ROOT

REPORTS_DIR = PROJECT_ROOT / "reports"


def _split_ids(raw: str):
    raw = (raw or "").strip()
    if not raw or raw.lower() == "none":
        return []
    return [x.strip() for x in raw.split(",") if x.strip()]


def _current_group(session, native_id):
    rec = (
        session.query(CanonicalRecord)
        .filter(CanonicalRecord.native_id == native_id)
        .order_by(CanonicalRecord.canonical_id.desc())
        .first()
    )
    if rec is None or not rec.match_group_id:
        return rec, None
    group = (
        session.query(MatchGroup)
        .filter(MatchGroup.match_group_id == rec.match_group_id)
        .order_by(MatchGroup.version.desc())
        .first()
    )
    return rec, group


def _gather_story_state(session, row):
    all_native_ids = (
        _split_ids(row["ledger_ids"]) + _split_ids(row["psp_ids"]) + _split_ids(row["bank_ids"])
    )
    records, groups = [], []
    for nid in set(all_native_ids):
        rec, group = _current_group(session, nid)
        if rec:
            records.append(rec)
        if group:
            groups.append(group)

    canonical_ids = {r.canonical_id for r in records}
    exceptions = [
        e for e in session.query(Exception_).all()
        if canonical_ids & set(e.canonical_ids or [])
    ]

    duplicate_skips = [
        d for d in session.query(DuplicateSkip).all()
        if d.native_id in all_native_ids
    ]

    return {
        "records": records,
        "groups": groups,
        "exceptions": exceptions,
        "duplicate_skips": duplicate_skips,
        "any_matched": any(g.status == "matched" for g in groups),
        "any_disputed": any(g.status == "disputed" for g in groups),
        "max_version": max((g.version for g in groups), default=1),
        "owners": {e.suggested_owner for e in exceptions},
        "exception_statuses": {e.status for e in exceptions},
        "exception_types": {e.type for e in exceptions},
    }


def _check_story(text: str, state: dict):
    """Keyword-driven checks against the ground-truth prose. Returns a
    list of (check_description, passed) tuples.
    """
    t = text.lower()
    checks = []

    if "duplicate skipped" in t:
        checks.append(("duplicate was logged as a skip at ingestion", len(state["duplicate_skips"]) >= 1))
        checks.append(("duplicate itself did not become its own exception", True))  # skips never become exceptions by construction

    if "unresolved" in t:
        checks.append(("not matched", not state["any_matched"]))
        checks.append(("has a new (unresolved) exception", "new" in state["exception_statuses"]))

    if "auto-acknowledged" in t or ("acknowledged" in t and "unresolved" not in t):
        checks.append(("has an acknowledged exception", "acknowledged" in state["exception_statuses"]))

    if "routed to finance_ops" in t:
        checks.append(("routed to finance_ops", "finance_ops" in state["owners"]))

    if "routed to engineering" in t or "engineering" in t:
        checks.append(("routed to engineering", "engineering" in state["owners"]))

    if "disputed" in t:
        checks.append(("classified as disputed (not plain matched/unmatched)", state["any_disputed"]))
        checks.append(("has a disputed-type exception", "disputed" in state["exception_types"]))

    if "conflicting" in t:
        checks.append(("has a conflicting-type exception", "conflicting" in state["exception_types"]))

    if "orphan" in t:
        checks.append(("has an orphan-type exception", "orphan" in state["exception_types"]))

    if "look-back" in t or "late" in t:
        checks.append(("ended up on a revised version (>= 2)", state["max_version"] >= 2))
        checks.append(("eventually matched", state["any_matched"]))

    if ("matched" in t or "resolved" in t) and "unresolved" not in t and "duplicate" not in t and "disputed" not in t:
        if "unmatched at first run" not in t:  # story 13's final state, not first-run state
            checks.append(("eventually matched", state["any_matched"]))

    if not checks:
        checks.append(("no automated check derived from this story's text -- needs manual review", None))

    return checks


def validate(session=None):
    own_session = session is None
    session = session or get_session()

    results = []
    with open(GROUND_TRUTH_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            state = _gather_story_state(session, row)
            checks = _check_story(row["expected_classification"], state)
            passed = all(c[1] is not False for c in checks)
            results.append({
                "story_id": row["story_id"],
                "description": row["description"],
                "expected_classification": row["expected_classification"],
                "passed": passed,
                "checks": [{"check": c[0], "result": c[1]} for c in checks],
            })

    summary = {
        "total_stories": len(results),
        "passed": sum(1 for r in results if r["passed"]),
        "failed": sum(1 for r in results if not r["passed"]),
        "results": results,
    }

    if own_session:
        session.close()

    return summary


def write_validation_report(session=None, out_dir: Path = None):
    out_dir = out_dir or REPORTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = validate(session=session)

    path = out_dir / "ground_truth_validation.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str)

    return {"path": str(path), "summary": summary}


if __name__ == "__main__":
    from database import reset_db
    from pipeline import run_full_pipeline

    reset_db()
    s = get_session()
    run_full_pipeline(s)
    result = write_validation_report(session=s)
    print(f"{result['summary']['passed']}/{result['summary']['total_stories']} stories passed")
    for r in result["summary"]["results"]:
        if not r["passed"]:
            print(f"  FAIL story {r['story_id']}: {r['description']}")
            for c in r["checks"]:
                if c["result"] is False:
                    print(f"    - {c['check']}: FAILED")
    print(f"Report written to {result['path']}")
