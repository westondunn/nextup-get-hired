from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest

from app import scoring
from app.relevance import MatchPreferences

TODAY = date(2026, 10, 30)


def job(**changes):
    values = dict(
        title="Head of QA",
        description="Python and C++ testing",
        company="Example",
        location="Springfield / Remote",
        posted_at=datetime(2026, 10, 30, tzinfo=UTC),
        date_kind="posted",
        score=100,
    )
    return SimpleNamespace(**(values | changes))


def profile(**changes):
    values = dict(
        skills=["Python", "C++"],
        target_titles=["Head of QA"],
        location="Springfield",
        work_preferences=["remote"],
    )
    return SimpleNamespace(**(values | changes))


def test_full_match_is_100_with_components_and_evidence():
    result = scoring.score_job(job(), profile(), TODAY)
    assert result["total"] == 100
    assert [part["points"] for part in result["components"]] == [35, 25, 10, 10, 10, 5, 5]
    assert sum(part["maximum"] for part in result["components"]) == 100
    assert all(part["evidence"] for part in result["components"])
    assert result["as_of"] == TODAY.isoformat() and result["version"] == scoring.VERSION


def test_whole_skill_phrases_and_repetition_do_not_inflate_scores():
    result = scoring.score_job(
        job(description="JavaScript JavaScript Python"), profile(skills=["Java", "Python"]), TODAY
    )
    skills = result["components"][0]
    assert skills["points"] == 18
    assert "Matched: Python" in skills["evidence"]
    assert "Not found: Java" in skills["evidence"]
    repeated = scoring.score_job(job(), profile(skills=["Python", "python", "PYTHON"]), TODAY)
    assert repeated["components"][0]["points"] == 35


def test_partial_title_has_lower_weight_and_multiple_targets_use_best_match():
    result = scoring.score_job(job(title="Senior QA"), profile(), TODAY)
    assert result["components"][1]["points"] == 6
    exact = scoring.score_job(
        job(title="Senior QA"), profile(target_titles=["Head of QA", "Senior QA"]), TODAY
    )
    assert exact["components"][1]["points"] == 25


@pytest.mark.parametrize("age,points", [(0, 5), (7, 5), (8, 2), (30, 2), (31, 0), (-1, 0)])
def test_provider_recency_boundaries_and_future_dates(age, points):
    result = scoring.score_job(
        job(
            posted_at=datetime(2026, 10, 30, tzinfo=UTC) - timedelta(days=age), date_kind="updated"
        ),
        profile(),
        TODAY,
    )
    assert result["components"][-1]["points"] == points
    if age >= 0:
        assert result["components"][-1]["evidence"][0].startswith("Updated")


def test_work_mode_uses_explicit_title_location_labels_only():
    assert (
        scoring.work_modes(job(location="Springfield", description="Collaborate with remote teams"))
        == []
    )
    assert scoring.work_modes(job(location="Springfield — not a remote role")) == []
    assert scoring.work_modes(job(location="Springfield — on-site")) == ["onsite"]
    assert scoring.work_modes(job(location="Hybrid — Springfield")) == ["hybrid"]


def test_cache_signature_changes_with_profile_job_date_or_rules(monkeypatch):
    original = scoring.cache_signature(job(), profile(), TODAY)
    assert original == scoring.cache_signature(job(), profile(), TODAY)
    assert original != scoring.cache_signature(job(), profile(skills=["Java"]), TODAY)
    assert original != scoring.cache_signature(job(description="Different"), profile(), TODAY)
    assert original != scoring.cache_signature(job(), profile(), TODAY + timedelta(days=1))
    monkeypatch.setattr(scoring, "VERSION", "test-rules-v2")
    assert original != scoring.cache_signature(job(), profile(), TODAY)
    monkeypatch.setattr(scoring, "VERSION", "rules-v3")
    assert original != scoring.cache_signature(
        job(), profile(), TODAY, MatchPreferences(needs_sponsorship=True)
    )


def component(result, key):
    return next(part for part in result["components"] if part["key"] == key)


def test_eligibility_quotes_statements_and_only_penalises_declared_needs():
    text = (
        "Python and C++ testing. We cannot sponsor visas; an active security clearance is required."
    )
    neutral = component(scoring.score_job(job(description=text), profile(), TODAY), "eligibility")
    assert neutral["points"] == 5 and neutral["maximum"] == 10
    assert any("sponsorship is not offered" in line for line in neutral["evidence"])
    assert any("Clearance statement" in line for line in neutral["evidence"])
    assert "Unmet per your preferences: clearance" in neutral["evidence"]
    cleared = component(
        scoring.score_job(
            job(description=text), profile(), TODAY, MatchPreferences(has_clearance=True)
        ),
        "eligibility",
    )
    assert cleared["points"] == 10
    sponsored = component(
        scoring.score_job(
            job(description=text),
            profile(),
            TODAY,
            MatchPreferences(has_clearance=True, needs_sponsorship=True),
        ),
        "eligibility",
    )
    assert (
        sponsored["points"] == 5
        and "Unmet per your preferences: sponsorship" in (sponsored["evidence"])
    )
    offered = component(
        scoring.score_job(
            job(description="Visa sponsorship available for this role."),
            profile(),
            TODAY,
            MatchPreferences(needs_sponsorship=True),
        ),
        "eligibility",
    )
    assert offered["points"] == 10 and any("offered" in line for line in offered["evidence"])
    citizen = component(
        scoring.score_job(job(description="US citizens only."), profile(), TODAY), "eligibility"
    )
    assert citizen["points"] == 10 and any("confirm eligibility" in e for e in citizen["evidence"])
    plain = component(scoring.score_job(job(), profile(), TODAY), "eligibility")
    assert "No sponsorship, clearance or citizenship statements detected." in plain["evidence"]


def test_eligibility_geographic_half_uses_the_allowed_location_phrases():
    outside = component(
        scoring.score_job(
            job(location="Remote Canada"), profile(), TODAY, MatchPreferences(locations=["US"])
        ),
        "eligibility",
    )
    assert outside["points"] == 5 and any("is outside" in line for line in outside["evidence"])
    inside = component(
        scoring.score_job(
            job(location="Springfield, US"), profile(), TODAY, MatchPreferences(locations=["US"])
        ),
        "eligibility",
    )
    assert inside["points"] == 10
    unchecked = component(scoring.score_job(job(), profile(), TODAY), "eligibility")
    assert "No allowed location phrases configured; label not checked." in unchecked["evidence"]


def test_responsibility_compares_listing_signals_with_the_wanted_level():
    manager = scoring.score_job(job(), profile(), TODAY)  # Head of QA wants management
    assert component(manager, "responsibility")["points"] == 5
    assert component(manager, "responsibility")["evidence"][1] == (
        "Wanted: management (from target titles)"
    )
    individual = scoring.score_job(
        job(title="Senior QA Engineer", description="Hands-on individual contributor"),
        profile(),
        TODAY,
    )
    assert component(individual, "responsibility")["points"] == 0
    assert component(individual, "responsibility")["evidence"][0].startswith(
        "Listing signals: individual"
    )
    unknown = scoring.score_job(job(title="QA Specialist"), profile(), TODAY)
    assert component(unknown, "responsibility")["points"] == 3
    mixed_targets = scoring.score_job(
        job(title="Senior QA Engineer", description="Hands-on individual contributor"),
        profile(target_titles=["Head of QA", "Senior QA Engineer"]),
        TODAY,
    )
    assert component(mixed_targets, "responsibility")["points"] == 5
    assert component(mixed_targets, "responsibility")["evidence"][1].startswith("Wanted: any")
    overridden = scoring.score_job(
        job(title="Senior QA Engineer", description="Hands-on individual contributor"),
        profile(),
        TODAY,
        MatchPreferences(responsibility="individual"),
    )
    assert component(overridden, "responsibility")["points"] == 5
    player_coach = scoring.score_job(
        job(description="Hands-on director with four direct reports"), profile(), TODAY
    )
    assert component(player_coach, "responsibility")["evidence"][0].startswith(
        "Listing signals: mixed"
    )


def test_filters_use_all_keywords_phrases_labels_and_score_bounds():
    options = dict(
        q="python testing",
        company="Example",
        location="Springfield",
        exclude="intern, junior",
        work_mode="remote",
        min_score=100,
        max_age_days=7,
        today=TODAY,
    )
    assert scoring.matches_filters(job(), **options)
    for changes in [
        dict(q="Java"),
        dict(company="Other"),
        dict(location="Shelbyville"),
        dict(exclude="head of qa"),
        dict(work_mode="onsite"),
    ]:
        assert not scoring.matches_filters(job(), **(options | changes))
    assert not scoring.matches_filters(job(score=None), **options)
    assert not scoring.matches_filters(job(posted_at=datetime(2026, 11, 1, tzinfo=UTC)), **options)


def rated(title, company="Example", rating=1):
    return scoring.RatedJob(title=title, company=company, rating=rating)


def ratings_part(result):
    return next(part for part in result["components"] if part["key"] == "ratings")


def test_ratings_add_no_component_until_something_is_rated():
    plain = scoring.score_job(job(), profile(), TODAY)
    assert all(part["key"] != "ratings" for part in plain["components"])
    assert plain == scoring.score_job(job(), profile(), TODAY, ratings=())


@pytest.mark.parametrize(
    "ratings,points",
    [
        ([rated("Head of QA")], 15),  # the job itself, or an identical one: full weight
        ([rated("Head of QA", rating=-1)], -15),
        ([rated("Head of QA", company="Elsewhere")], 15),  # same title, other employer
        ([rated("Head of QA Engineering", company="Elsewhere")], 10),  # 2 of 3 title words
        ([rated("Head of QA Engineering")], 14),  # the same employer adds 0.25
        ([rated("Head of Quality Assurance", company="Elsewhere")], 0),  # 1 of 4: too far
        ([rated("Head of Quality Assurance")], 8),  # the employer bonus lifts it past the floor
        ([rated("Payroll Specialist")], 0),  # not similar enough to count
        ([rated("Head of QA"), rated("Head of QA", company="Other", rating=-1)], 0),
    ],
)
def test_ratings_move_similar_jobs_by_up_to_fifteen_points(ratings, points):
    assert (
        ratings_part(scoring.score_job(job(), profile(), TODAY, ratings=ratings))["points"]
        == points
    )


def test_ratings_explain_the_rated_jobs_and_keep_the_total_within_bounds():
    liked = scoring.score_job(job(), profile(), TODAY, ratings=[rated("Head of QA")])
    assert liked["total"] == 100, "capped at 100"
    part = ratings_part(liked)
    assert part["maximum"] == 15
    assert part["evidence"] == ["More like this: Head of QA at Example (100% similar)."]
    weak = job(title="Payroll Head", description="", location="Elsewhere", date_kind="observed")
    nurse = profile(target_titles=["Staff Nurse"])
    assert scoring.score_job(weak, nurse, TODAY)["total"] == 10
    passed = scoring.score_job(weak, nurse, TODAY, ratings=[rated("Payroll Head", rating=-1)])
    assert passed["total"] == 0, "never below 0"
    unrelated = scoring.score_job(job(), profile(), TODAY, ratings=[rated("Payroll Specialist")])
    assert ratings_part(unrelated)["evidence"] == ["Not similar to any of the 1 jobs you rated."]


def test_ratings_are_part_of_the_cache_signature():
    base = scoring.cache_signature(job(), profile(), TODAY)
    liked = scoring.cache_signature(job(), profile(), TODAY, ratings=[rated("Head of QA")])
    passed = scoring.cache_signature(
        job(), profile(), TODAY, ratings=[rated("Head of QA", rating=-1)]
    )
    assert len({base, liked, passed}) == 3
