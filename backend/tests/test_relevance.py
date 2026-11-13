from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.relevance import MatchPreferences, location_matches, role_matches

# One user's vocabulary, as it would be saved in their match preferences.
ALIASES = {"qa": "quality assurance", "qe": "quality engineering", "sdet": "test automation"}
SPECIALTIES = (
    "sales engineering",
    "asset quality",
    "credit quality",
    "product quality",
    "quality control",
)


@pytest.mark.parametrize(
    "label,accepted",
    [
        ("Remote US", True),
        ("United States | Remote", True),
        ("U.S. Remote", True),
        ("U.S.A. / Remote", True),
        ("Springfield / Hybrid", True),
        ("United States / Canada", True),
        ("Remote Canada", False),
        ("Remote Poland", False),
        ("Australia", False),
        ("Remote", False),
        ("New York, NY", False),
        ("Outside US", False),
        ("Non-US remote", False),
        ("United States excluded", False),
    ],
)
def test_explicit_location_phrases_are_not_substrings_or_country_guesses(label, accepted):
    preferences = MatchPreferences(locations=["US", "USA", "United States", "Springfield"])
    assert location_matches(label, preferences) is accepted


def test_unknown_locations_are_explicit_and_never_include_named_other_regions():
    preferences = MatchPreferences(locations=["US"], include_unspecified_location=True)
    assert location_matches("Remote", preferences)
    assert location_matches("Worldwide", preferences)
    assert not location_matches("Remote Canada", preferences)
    assert not location_matches("London", preferences)
    assert location_matches("Remote Canada", MatchPreferences())


@pytest.mark.parametrize("value", [["---"], ["x" * 101], ["US"] * 21, ["bad\x00place"]])
def test_location_validation(value):
    with pytest.raises(ValidationError):
        MatchPreferences(locations=value)


def test_location_terms_deduplicate_equivalent_country_abbreviations():
    assert MatchPreferences(locations=[" US ", "us", "U.S.", "Springfield"]).locations == [
        "US",
        "Springfield",
    ]


@pytest.mark.parametrize(
    "title,accepted",
    [
        ("Director of Quality Engineering", True),
        ("Head of QA", True),
        ("VP, Software Engineering", True),
        ("Senior Engineering Manager", True),
        ("Director of Sales", False),
        ("Senior Technical Account Manager", False),
        ("Staff Technical Program Manager, Engineering Onboarding", False),
        ("Director, Technical Program Management", False),
        ("Senior Product Manager", False),
        ("Staff Software Engineer", False),
        ("Manager", False),
        ("Senior Manager, Asset Quality & Model Oversight", False),
        ("Senior Operations Manager, Quality Control", False),
        ("Director, Enterprise Sales Engineering", False),
        ("Product Quality Manager, Home Lending", False),
        ("Director of Quality Control", False),
    ],
)
def test_leadership_requires_title_discipline_and_correct_function(title, accepted):
    profile = SimpleNamespace(
        target_titles=["Head of Quality Assurance", "Director of Engineering"]
    )
    assert role_matches(title, profile, "auto", ALIASES, SPECIALTIES) is accepted


def test_no_field_vocabulary_is_built_in():
    profile = SimpleNamespace(target_titles=["Head of Quality Assurance"])
    assert MatchPreferences().title_aliases == {} and MatchPreferences().other_specialties == []
    # Without the user's abbreviation the short form is just another word...
    assert not role_matches("Head of QA", profile, "auto")
    assert role_matches("Head of QA", profile, "auto", ALIASES)
    # ...and without the user's list no specialty is treated as a different one.
    assert role_matches("Director of Quality Control", profile, "auto")
    assert not role_matches("Director of Quality Control", profile, "auto", ALIASES, SPECIALTIES)


def test_vocabulary_is_normalized_and_validated():
    preferences = MatchPreferences(
        title_aliases={" QA ": "Quality  Assurance"},
        other_specialties=["Quality Control", "quality control", " Sales-Engineering "],
    )
    assert preferences.title_aliases == {"qa": "quality assurance"}
    assert preferences.other_specialties == ["quality control", "sales engineering"]
    for bad in (
        {"title_aliases": {"two words": "x"}},
        {"title_aliases": {"qa": "---"}},
        {"title_aliases": {f"a{i}": "b" for i in range(21)}},
        {"other_specialties": ["---"]},
        {"other_specialties": ["x" * 61]},
    ):
        with pytest.raises(ValidationError):
            MatchPreferences(**bad)


def test_function_is_allowed_when_targeted_and_nonleadership_preferences_are_supported():
    assert role_matches(
        "Director of Quality Control",
        SimpleNamespace(target_titles=["Director of Quality Control"]),
        "strict",
    )
    assert role_matches(
        "Technical Program Manager, Engineering",
        SimpleNamespace(target_titles=["Director of Program Management"]),
        "strict",
    )
    mixed = SimpleNamespace(target_titles=["Director of Engineering", "Software Engineer"])
    assert role_matches("Staff Software Engineer", mixed, "auto")
    assert not role_matches("Staff Software Engineer", mixed, "strict")
    assert role_matches("Staff Software Engineer", mixed, "any")
