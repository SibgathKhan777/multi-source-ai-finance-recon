"""Phase 7 — reporting.

match_rate = matched_count / total_canonical_records

Produces one JSON and one CSV report: the match rate, counts by category,
and every unresolved exception with its reason, suggested owner and status.
"""
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from database import get_session
from models import CanonicalRecord, MatchGroup, Exception_
from config import PROJECT_ROOT

REPORTS_DIR = PROJECT_ROOT / "reports"


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _current_status_counts(session):
    group_ids = sorted({
        row[0] for row in session.query(CanonicalRecord.match_group_id).all() if row[0]
    })
    counts = {"matched": 0, "partial": 0, "unmatched": 0, "disputed": 0}
    for gid in group_ids:
        group = (
            session.query(MatchGroup)
            .filter(MatchGroup.match_group_id == gid)
            .order_by(MatchGroup.version.desc())
            .first()
        )
        if group:
            counts[group.status] = counts.get(group.status, 0) + 1
    return counts


def build_report(session=None):
    own_session = session is None
    session = session or get_session()

    total_canonical = session.query(CanonicalRecord).count()

    # a match_group_id can have multiple versions, so status is resolved via
    # each group's *current* (latest, non-superseded) version, not a raw join
    group_ids = sorted({
        row[0] for row in session.query(CanonicalRecord.match_group_id).all() if row[0]
    })
    current_status = {}
    for gid in group_ids:
        group = (
            session.query(MatchGroup)
            .filter(MatchGroup.match_group_id == gid)
            .order_by(MatchGroup.version.desc())
            .first()
        )
        if group:
            current_status[gid] = group.status

    matched_canonical = sum(
        1 for r in session.query(CanonicalRecord).all()
        if r.match_group_id and current_status.get(r.match_group_id) == "matched"
    )

    match_rate = round(matched_canonical / total_canonical, 4) if total_canonical else 0.0
    group_counts = _current_status_counts(session)

    exceptions = session.query(Exception_).order_by(Exception_.exception_id).all()
    unresolved = [e for e in exceptions if e.status == "new"]

    report = {
        "generated_at": _now_iso(),
        "match_rate": match_rate,
        "total_canonical_records": total_canonical,
        "matched_canonical_records": matched_canonical,
        "match_group_status_counts": group_counts,
        "exception_counts_by_type": _count_by(exceptions, "type"),
        "exception_counts_by_status": _count_by(exceptions, "status"),
        "unresolved_exceptions": [
            {
                "exception_id": e.exception_id,
                "type": e.type,
                "detail": e.detail,
                "suggested_owner": e.suggested_owner,
                "status": e.status,
                "canonical_ids": e.canonical_ids,
            }
            for e in unresolved
        ],
        "all_exceptions": [
            {
                "exception_id": e.exception_id,
                "type": e.type,
                "detail": e.detail,
                "suggested_owner": e.suggested_owner,
                "status": e.status,
                "acknowledged_by": e.acknowledged_by,
            }
            for e in exceptions
        ],
    }

    if own_session:
        session.close()

    return report


def _count_by(items, attr):
    out = {}
    for item in items:
        key = getattr(item, attr)
        out[key] = out.get(key, 0) + 1
    return out


def write_report(session=None, out_dir: Path = None):
    out_dir = out_dir or REPORTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    report = build_report(session=session)

    json_path = out_dir / "reconciliation_report.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)

    csv_path = out_dir / "reconciliation_report.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["match_rate", report["match_rate"]])
        writer.writerow(["total_canonical_records", report["total_canonical_records"]])
        writer.writerow(["matched_canonical_records", report["matched_canonical_records"]])
        writer.writerow([])
        writer.writerow(["exception_id", "type", "detail", "suggested_owner", "status"])
        for e in report["all_exceptions"]:
            writer.writerow([e["exception_id"], e["type"], e["detail"], e["suggested_owner"], e["status"]])

    return {"json_path": str(json_path), "csv_path": str(csv_path), "report": report}
