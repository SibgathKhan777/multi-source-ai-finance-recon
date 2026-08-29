"""FastAPI app tying every phase together behind a small HTTP API for the
Phase 8 frontend (plus a few API-only endpoints -- rules editor, version
browser, manual reprocessing trigger -- that intentionally have no UI yet,
per the build prompt's Phase 8 scope).
"""
from typing import Optional

from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from database import init_db, get_session, SessionLocal
from models import CanonicalRecord, MatchGroup, RawRecord, Exception_, Rule
from pipeline import run_full_pipeline
from reprocessing.late_arrival import process_late_arrivals
from exceptions.generate import acknowledge_exception, generate_exceptions
from reporting.report import build_report
from reporting.validate import validate as validate_ground_truth

app = FastAPI(title="Multi-Source Finance Reconciliation API")

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://localhost:\d+",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@app.on_event("startup")
def on_startup():
    init_db()
    session = get_session()
    try:
        has_data = session.query(CanonicalRecord).count() > 0
        if not has_data:
            run_full_pipeline(session)
    finally:
        session.close()


# ---- reporting -----------------------------------------------------

@app.get("/api/report")
def get_report(db=Depends(get_db)):
    return build_report(session=db)


@app.get("/api/validation")
def get_validation(db=Depends(get_db)):
    return validate_ground_truth(session=db)


# ---- exceptions (Phase 8 UI: table + detail + acknowledge) --------

def _exception_to_dict(exc: Exception_, db) -> dict:
    return {
        "exception_id": exc.exception_id,
        "type": exc.type,
        "detail": exc.detail,
        "status": exc.status,
        "suggested_owner": exc.suggested_owner,
        "canonical_ids": exc.canonical_ids,
        "created_at": exc.created_at,
        "acknowledged_at": exc.acknowledged_at,
        "acknowledged_by": exc.acknowledged_by,
    }


@app.get("/api/exceptions")
def list_exceptions(status: Optional[str] = None, type: Optional[str] = None, db=Depends(get_db)):
    query = db.query(Exception_)
    if status:
        query = query.filter(Exception_.status == status)
    if type:
        query = query.filter(Exception_.type == type)
    exceptions = query.order_by(Exception_.exception_id).all()
    return [_exception_to_dict(e, db) for e in exceptions]


@app.get("/api/exceptions/{exception_id}")
def get_exception_detail(exception_id: str, db=Depends(get_db)):
    exc = db.get(Exception_, exception_id)
    if exc is None:
        raise HTTPException(status_code=404, detail="exception not found")

    records = []
    for cid in exc.canonical_ids or []:
        rec = db.get(CanonicalRecord, cid)
        if rec is None:
            continue
        raw = db.get(RawRecord, rec.raw_id)
        records.append({
            "canonical_id": rec.canonical_id,
            "source": rec.source,
            "native_id": rec.native_id,
            "amount": rec.amount,
            "currency": rec.currency,
            "counterparty_id": rec.counterparty_id,
            "state": rec.state,
            "raw_payload": raw.raw_payload if raw else None,
            "validation_status": raw.validation_status if raw else None,
            "flag_reason": raw.flag_reason if raw else None,
        })

    return {**_exception_to_dict(exc, db), "records": records}


class AcknowledgeBody(BaseModel):
    acknowledged_by: str = "finance_ops_user"


@app.post("/api/exceptions/{exception_id}/acknowledge")
def acknowledge(exception_id: str, body: AcknowledgeBody, db=Depends(get_db)):
    exc = acknowledge_exception(db, exception_id, acknowledged_by=body.acknowledged_by)
    if exc is None:
        raise HTTPException(status_code=404, detail="exception not found")
    db.commit()
    return _exception_to_dict(exc, db)


# ---- API-only: rules table editor (Phase 5, finance_ops self-service) --

class RuleBody(BaseModel):
    rule_id: str
    condition: dict
    action: str
    owner: Optional[str] = None
    active: bool = True


@app.get("/api/rules")
def list_rules(db=Depends(get_db)):
    return [
        {"rule_id": r.rule_id, "condition": r.condition, "action": r.action, "owner": r.owner, "active": r.active}
        for r in db.query(Rule).order_by(Rule.rule_id).all()
    ]


@app.post("/api/rules")
def upsert_rule(body: RuleBody, db=Depends(get_db)):
    from datetime import datetime, timezone

    rule = db.get(Rule, body.rule_id)
    if rule is None:
        rule = Rule(rule_id=body.rule_id, created_at=datetime.now(timezone.utc).isoformat())
        db.add(rule)
    rule.condition = body.condition
    rule.action = body.action
    rule.owner = body.owner
    rule.active = body.active
    db.commit()
    return {"rule_id": rule.rule_id, "condition": rule.condition, "action": rule.action, "owner": rule.owner, "active": rule.active}


# ---- API-only: match-group version / audit-trail browser (Phase 6) ----

@app.get("/api/match-groups/{match_group_id}/versions")
def match_group_versions(match_group_id: str, db=Depends(get_db)):
    versions = (
        db.query(MatchGroup)
        .filter(MatchGroup.match_group_id == match_group_id)
        .order_by(MatchGroup.version.asc())
        .all()
    )
    if not versions:
        raise HTTPException(status_code=404, detail="match group not found")
    return [
        {
            "version": v.version,
            "status": v.status,
            "method": v.method,
            "revision_reason": v.revision_reason,
            "closed_at": v.closed_at,
            "detail": v.detail,
            "member_canonical_ids": [m.canonical_id for m in v.members],
        }
        for v in versions
    ]


# ---- API-only: manual pipeline / reprocessing triggers ----------------

@app.post("/api/reprocess")
def trigger_reprocess(look_back_days: Optional[int] = None, db=Depends(get_db)):
    result = process_late_arrivals(session=db, look_back_days=look_back_days)
    generate_exceptions(session=db)
    db.commit()
    return result


@app.post("/api/run-pipeline")
def trigger_full_run(db=Depends(get_db)):
    from database import reset_db

    reset_db()
    fresh = SessionLocal()
    try:
        result = run_full_pipeline(fresh)
        return result
    finally:
        fresh.close()
