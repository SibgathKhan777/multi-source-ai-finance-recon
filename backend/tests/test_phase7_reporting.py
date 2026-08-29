from pipeline import run_full_pipeline
from reporting.report import build_report
from reporting.validate import validate


def _setup(session):
    return run_full_pipeline(session)


def test_match_rate_is_matched_over_total(db_session):
    _setup(db_session)
    report = build_report(session=db_session)
    assert report["total_canonical_records"] == 67
    expected_rate = round(report["matched_canonical_records"] / report["total_canonical_records"], 4)
    assert report["match_rate"] == expected_rate
    assert 0 < report["match_rate"] < 1


def test_report_lists_every_unresolved_exception_with_reason(db_session):
    _setup(db_session)
    report = build_report(session=db_session)
    assert len(report["unresolved_exceptions"]) >= 1
    for exc in report["unresolved_exceptions"]:
        assert exc["detail"]
        assert exc["suggested_owner"] in ("engineering", "finance_ops")
        assert exc["status"] == "new"


def test_exactly_five_stories_remain_genuinely_unresolved(db_session):
    _setup(db_session)
    report = build_report(session=db_session)
    # stories 10, 14, 15, 18, 20 are the ones ground truth says should NOT
    # cleanly resolve (18 is disputed, not "new", but still not matched)
    unresolved_new = [e for e in report["all_exceptions"] if e["status"] == "new"]
    assert len(unresolved_new) == 5


def test_ground_truth_validation_all_stories_pass(db_session):
    _setup(db_session)
    summary = validate(session=db_session)
    failed = [r for r in summary["results"] if not r["passed"]]
    assert failed == [], f"stories failing validation: {[(r['story_id'], r['checks']) for r in failed]}"
    assert summary["total_stories"] == 20
    assert summary["passed"] == 20


def test_ground_truth_validation_is_automated_not_hand_verified(db_session):
    _setup(db_session)
    summary = validate(session=db_session)
    # every story must have derived at least one real check (not just the
    # "needs manual review" fallback), proving the comparison is automated
    for r in summary["results"]:
        checks = [c["check"] for c in r["checks"]]
        assert "no automated check derived from this story's text -- needs manual review" not in checks, (
            f"story {r['story_id']} has no automated check"
        )
