from sqlalchemy import (
    Column,
    String,
    Float,
    Boolean,
    Integer,
    DateTime,
    JSON,
    ForeignKey,
    Text,
)
from sqlalchemy.orm import relationship

from database import Base


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"

    run_id = Column(String, primary_key=True)
    started_at = Column(String, nullable=False)
    look_back_days = Column(Integer, nullable=False)
    rows_processed = Column(Integer, default=0)
    duplicates_skipped = Column(Integer, default=0)
    flagged_rows = Column(Integer, default=0)


class RawRecord(Base):
    __tablename__ = "raw_records"

    raw_id = Column(String, primary_key=True)
    source = Column(String, nullable=False)  # ledger|psp|bank
    ingestion_run_id = Column(String, ForeignKey("ingestion_runs.run_id"), nullable=False)
    dedup_key = Column(String, nullable=False, index=True)
    native_id = Column(String, nullable=False, index=True)
    validation_status = Column(String, nullable=False)  # valid|flagged
    flag_reason = Column(String, nullable=True)
    raw_payload = Column(JSON, nullable=False)
    ingested_at = Column(String, nullable=False)


class DuplicateSkip(Base):
    __tablename__ = "duplicate_skips"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source = Column(String, nullable=False)
    native_id = Column(String, nullable=False)
    dedup_key = Column(String, nullable=False, index=True)
    ingestion_run_id = Column(String, ForeignKey("ingestion_runs.run_id"), nullable=False)
    original_raw_id = Column(String, nullable=False)
    skipped_at = Column(String, nullable=False)


class Crosswalk(Base):
    __tablename__ = "crosswalk"

    id = Column(Integer, primary_key=True, autoincrement=True)
    native_name = Column(String, nullable=False, unique=True, index=True)
    counterparty_id = Column(String, nullable=False, index=True)


class CanonicalRecord(Base):
    __tablename__ = "canonical_records"

    canonical_id = Column(String, primary_key=True)
    raw_id = Column(String, ForeignKey("raw_records.raw_id"), nullable=False)
    source = Column(String, nullable=False)
    native_id = Column(String, nullable=False, index=True)
    amount = Column(Float, nullable=False)  # signed, as reported by source
    currency = Column(String, nullable=True)
    currency_inferred = Column(Boolean, default=False)
    counterparty_raw = Column(String, nullable=True)
    counterparty_id = Column(String, nullable=True, index=True)
    ts_utc = Column(DateTime, nullable=True)
    ts_precision = Column(String, nullable=False, default="exact")  # exact|date_only|missing
    event_type = Column(String, nullable=False, default="payment")  # payment|refund|chargeback|settlement
    state = Column(String, nullable=False)  # initiated|authorized|captured|settled|refunded|disputed
    settlement_batch_id = Column(String, nullable=True, index=True)
    fee = Column(Float, nullable=True)
    related_native_id = Column(String, nullable=True)
    extra = Column(JSON, nullable=True)

    match_group_id = Column(String, nullable=True, index=True)  # business id, latest version
    created_at = Column(String, nullable=False)


class MatchGroup(Base):
    __tablename__ = "match_groups"

    id = Column(Integer, primary_key=True, autoincrement=True)
    match_group_id = Column(String, nullable=False, index=True)  # business id, stable across versions
    version = Column(Integer, nullable=False, default=1)
    status = Column(String, nullable=False)  # matched|unmatched|partial
    method = Column(String, nullable=True)
    revision_reason = Column(String, nullable=True)
    previous_version_id = Column(Integer, ForeignKey("match_groups.id"), nullable=True)
    closed_at = Column(String, nullable=True)
    detail = Column(JSON, nullable=True)
    created_at = Column(String, nullable=False)

    members = relationship("MatchGroupMember", backref="group", cascade="all, delete-orphan")


class MatchGroupMember(Base):
    __tablename__ = "match_group_members"

    id = Column(Integer, primary_key=True, autoincrement=True)
    match_group_row_id = Column(Integer, ForeignKey("match_groups.id"), nullable=False)
    canonical_id = Column(String, ForeignKey("canonical_records.canonical_id"), nullable=False)


class Exception_(Base):
    __tablename__ = "exceptions"

    exception_id = Column(String, primary_key=True)
    fingerprint = Column(String, nullable=False, index=True)
    type = Column(String, nullable=False)  # conflicting|unmatched|partial|orphan|disputed
    detail = Column(Text, nullable=False)
    status = Column(String, nullable=False, default="new")  # new|acknowledged
    suggested_owner = Column(String, nullable=False)  # engineering|finance_ops
    match_group_id = Column(String, nullable=True)
    canonical_ids = Column(JSON, nullable=True)
    story_id = Column(String, nullable=True)
    created_at = Column(String, nullable=False)
    acknowledged_at = Column(String, nullable=True)
    acknowledged_by = Column(String, nullable=True)


class Rule(Base):
    __tablename__ = "rules"

    rule_id = Column(String, primary_key=True)
    condition = Column(JSON, nullable=False)
    action = Column(String, nullable=False)  # auto_acknowledge|route
    owner = Column(String, nullable=True)
    active = Column(Boolean, default=True)
    created_at = Column(String, nullable=False)


class AgentDecision(Base):
    __tablename__ = "agent_decisions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    canonical_ids = Column(JSON, nullable=False)
    resolved = Column(Boolean, nullable=False)
    reason = Column(Text, nullable=False)
    action = Column(String, nullable=True)  # e.g. infer_currency, relax_tolerance, crosswalk_resolve, refund_net
    created_at = Column(String, nullable=False)
