import csv

from ingestion.pipeline import run_ingestion
from normalization.normalize import run_normalization
from matching.engine import run_matching
from agent.reasoning import run_agent
from exceptions.generate import generate_exceptions
from reprocessing.late_arrival import process_late_arrivals
from models import CanonicalRecord, MatchGroup, Exception_
from config import LEDGER_CSV, PSP_CSV, BANK_CSV


def _bank_csv_without_late_row(tmp_path):
    out_path = tmp_path / "bank_statement_no_late.csv"
    with open(BANK_CSV, newline="", encoding="utf-8") as src, open(out_path, "w", newline="", encoding="utf-8") as dst:
        reader = csv.DictReader(src)
        writer = csv.DictWriter(dst, fieldnames=reader.fieldnames)
        writer.writeheader()
        for row in reader:
            if row["ref_no"] != "NEFT-7001":
                writer.writerow(row)
    return out_path


def _full_pipeline(session, bank_path):
    run_ingestion(sources={"ledger": LEDGER_CSV, "psp": PSP_CSV, "bank": bank_path}, session=session)
    session.commit()
    run_normalization(session=session)
    session.commit()
    run_matching(session=session)
    session.commit()
    run_agent(session=session)
    session.commit()
    generate_exceptions(session=session)
    session.commit()


def _current_group(session, native_id, source="ledger"):
    rec = (
        session.query(CanonicalRecord)
        .filter(CanonicalRecord.native_id == native_id, CanonicalRecord.source == source)
        .first()
    )
    return session.query(MatchGroup).filter(MatchGroup.match_group_id == rec.match_group_id).order_by(MatchGroup.version.desc()).first()


def test_first_run_leaves_story13_unmatched(db_session, tmp_path):
    bank_path = _bank_csv_without_late_row(tmp_path)
    _full_pipeline(db_session, bank_path)

    group = _current_group(db_session, "LDG-7001")
    assert group.status == "partial"
    assert group.version == 1


def test_late_arrival_produces_version2_matched_preserving_version1(db_session, tmp_path):
    bank_path = _bank_csv_without_late_row(tmp_path)
    _full_pipeline(db_session, bank_path)

    v1_group = _current_group(db_session, "LDG-7001")
    v1_id = v1_group.id
    assert v1_group.version == 1
    assert v1_group.status == "partial"

    # late row arrives: re-ingest with the FULL bank CSV (dedup skips
    # everything already seen, only NEFT-7001 is new)
    run_ingestion(session=db_session)
    db_session.commit()
    result = process_late_arrivals(session=db_session)
    db_session.commit()

    assert len(result["revisions"]) == 1
    assert result["revisions"][0]["revision_reason"] == "late bank record arrived (NEFT-7001)"

    v2_group = _current_group(db_session, "LDG-7001")
    assert v2_group.version == 2
    assert v2_group.status == "matched"
    assert v2_group.previous_version_id == v1_id
    assert v2_group.match_group_id == v1_group.match_group_id  # same business id

    # version 1 must still exist, untouched, just marked closed
    v1_reloaded = db_session.get(MatchGroup, v1_id)
    assert v1_reloaded.status == "partial"
    assert v1_reloaded.version == 1
    assert v1_reloaded.closed_at is not None


def test_late_arrival_acknowledges_the_old_partial_exception(db_session, tmp_path):
    bank_path = _bank_csv_without_late_row(tmp_path)
    _full_pipeline(db_session, bank_path)

    old_exc = None
    for exc in db_session.query(Exception_).all():
        recs = [db_session.get(CanonicalRecord, cid) for cid in exc.canonical_ids]
        if any(r.native_id == "LDG-7001" for r in recs):
            old_exc = exc
    assert old_exc is not None
    assert old_exc.status == "new"

    run_ingestion(session=db_session)
    db_session.commit()
    process_late_arrivals(session=db_session)
    db_session.commit()

    refreshed = db_session.get(Exception_, old_exc.exception_id)
    assert refreshed.status == "acknowledged"
    assert refreshed.acknowledged_by == "system:late_arrival_reprocessing"
