"""Runs all phases end to end, in order, against a single session."""
from ingestion.pipeline import run_ingestion
from normalization.normalize import run_normalization
from matching.engine import run_matching
from agent.reasoning import run_agent
from exceptions.generate import generate_exceptions
from reprocessing.late_arrival import process_late_arrivals


def run_full_pipeline(session, sources=None, look_back_days=None):
    ingestion_result = run_ingestion(sources=sources, session=session)
    session.commit()

    normalization_result = run_normalization(session=session)
    session.commit()

    matching_result = run_matching(session=session)
    session.commit()

    agent_result = run_agent(session=session)
    session.commit()

    exceptions_result = generate_exceptions(session=session)
    session.commit()

    reprocessing_result = process_late_arrivals(session=session, look_back_days=look_back_days)
    session.commit()

    # a late-arrival revision can close a group that had triggered an
    # exception moments earlier in this same run -- nothing new should be
    # unresolved as a result, but re-running is cheap and keeps the
    # exception set consistent with the final match-group state.
    exceptions_result = generate_exceptions(session=session)
    session.commit()

    return {
        "ingestion": ingestion_result,
        "normalization": normalization_result,
        "matching": matching_result,
        "agent": agent_result,
        "exceptions": exceptions_result,
        "reprocessing": reprocessing_result,
    }
