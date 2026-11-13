"""Explainable label matching; never infer work authorization or people-management history."""

import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app import scoring

TitleTerm = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=60, pattern=r"^[^\x00]+$"),
]
LocationTerm = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=100, pattern=r"^[^\x00]+$"),
]


class MatchPreferences(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    locations: list[LocationTerm] = Field(default_factory=list, max_length=20)
    include_unspecified_location: bool = False
    leadership: Literal["auto", "strict", "any"] = "auto"
    # Stated by the user, never inferred: scoring only compares them with listing text.
    needs_sponsorship: bool = False
    has_clearance: bool = False
    responsibility: Literal["auto", "management", "individual", "any"] = "auto"
    # Vocabulary of the user's own field; nothing profession-specific is built in.
    # An abbreviation and what it stands for in job titles, e.g. {"qa": "quality assurance"}.
    title_aliases: dict[TitleTerm, TitleTerm] = Field(default_factory=dict, max_length=20)
    # Phrases that mark a different specialty, e.g. "quality control" for someone in software
    # quality. A leadership title containing one is rejected unless a target title has it too.
    other_specialties: list[TitleTerm] = Field(default_factory=list, max_length=20)

    @field_validator("locations")
    @classmethod
    def clean_locations(cls, values):
        result, seen = [], set()
        for value in values:
            key = tuple(location_tokens(value))
            if not key:
                raise ValueError("Location phrases must contain letters or numbers")
            if key not in seen:
                seen.add(key)
                result.append(value)
        return result

    @field_validator("title_aliases")
    @classmethod
    def clean_aliases(cls, values):
        result = {}
        for short, full in values.items():
            key, words = scoring.tokens(short), scoring.tokens(full)
            if len(key) != 1 or not words:
                raise ValueError("An abbreviation is one word and stands for at least one word")
            result[key[0]] = " ".join(words)
        return result

    @field_validator("other_specialties")
    @classmethod
    def clean_specialties(cls, values):
        result = []
        for value in values:
            phrase = " ".join(scoring.tokens(value))
            if not phrase:
                raise ValueError("A specialty must contain letters or numbers")
            if phrase not in result:
                result.append(phrase)
        return result


def location_tokens(value):
    # Common country abbreviations remain whole tokens; 'US' never matches 'Australia'.
    value = re.sub(r"\bu\.s\.a\.?", "USA", value, flags=re.I)
    value = re.sub(r"\bu\.s\.?", "US", value, flags=re.I)
    return scoring.tokens(value)


def location_matches(location, preferences):
    if not preferences.locations:
        return True
    words = location_tokens(location)
    if any(
        scoring.contains_phrase(words, location_tokens(term))
        and not any(
            scoring.contains_phrase(words, scoring.tokens(prefix) + location_tokens(term))
            for prefix in ("not", "non", "outside", "outside of", "not in", "except", "excluding")
        )
        and not any(
            scoring.contains_phrase(words, location_tokens(term) + scoring.tokens(suffix))
            for suffix in ("excluded", "not eligible", "not supported")
        )
        for term in preferences.locations
    ):
        return True
    unspecified = {
        "remote",
        "hybrid",
        "onsite",
        "on site",
        "location not specified",
        "not specified",
        "anywhere",
        "worldwide",
        "global",
        "remote worldwide",
        "remote global",
        "multiple locations",
        "remote eligible",
    }
    return preferences.include_unspecified_location and " ".join(words) in unspecified


LEADERS = {"director", "head", "vp", "svp", "evp", "president", "manager", "chief"}
GENERIC = (
    LEADERS
    | scoring.TITLE_STOP_WORDS
    | {
        "senior",
        "sr",
        "associate",
        "assistant",
        "vice",
        "technical",
        "staff",
        "executive",
    }
)
OTHER_FUNCTIONS = (
    "program",
    "project",
    "product",
    "account",
    "sales",
    "marketing",
    "customer success",
    "recruiting",
    "operations",
)


def title_tokens(value, aliases=None):
    """Title words, with each of the user's abbreviations replaced by what it stands for."""
    aliases = aliases or {}
    return [part for word in scoring.tokens(value) for part in aliases.get(word, word).split()]


def role_matches(title, profile, mode, aliases=None, specialties=()):
    targets = [title_tokens(t, aliases) for t in profile.target_titles]
    required = mode == "strict" or (
        mode == "auto" and bool(targets) and all(set(t) & LEADERS for t in targets)
    )
    if not required:
        return True
    words = title_tokens(title, aliases)
    if not set(words) & LEADERS:
        return False
    for specialty in specialties:
        phrase = scoring.tokens(specialty)
        if scoring.contains_phrase(words, phrase) and not any(
            scoring.contains_phrase(target, phrase) for target in targets
        ):
            return False
    # A program, account or product manager is a different function from leading a
    # discipline. Permit it when that function is itself a saved target.
    for function in OTHER_FUNCTIONS:
        domain = scoring.tokens(function)
        is_other_function = any(
            scoring.contains_phrase(words, phrase)
            for phrase in (domain + ["manager"], domain + ["management"], ["manager"] + domain)
        )
        if is_other_function and not any(scoring.contains_phrase(t, domain) for t in targets):
            return False
    discipline = set(words) - GENERIC
    return any((set(target) - GENERIC) & discipline for target in targets)
