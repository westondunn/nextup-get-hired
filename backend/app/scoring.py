"""Deterministic local ranking. Scores are evidence counts, not hiring probabilities."""

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, date, datetime

from app.companies import normalize_company_name

VERSION = "rules-v4"
TITLE_STOP_WORDS = {"a", "an", "and", "for", "in", "of", "the", "to"}

# Lexical statements employers make about eligibility. They are quoted as evidence and
# compared with what the user declared in match preferences; nothing is inferred.
SPONSORSHIP_DENIED = (
    "no sponsorship",
    "no visa sponsorship",
    "not sponsor",
    "cannot sponsor",
    "can t sponsor",
    "unable to sponsor",
    "without sponsorship",
    "sponsorship is not available",
    "sponsorship not available",
    "sponsorship is unavailable",
    "not provide sponsorship",
    "not offer sponsorship",
    "not eligible for sponsorship",
    "not available for sponsorship",
)
SPONSORSHIP_OFFERED = ("sponsorship available", "sponsorship is available", "will sponsor")
AUTHORIZATION_REQUIRED = (
    "authorized to work",
    "authorization to work",
    "work authorization",
    "legally authorized",
    "eligible to work in",
)
CLEARANCE_REQUIRED = (
    "security clearance",
    "active clearance",
    "clearance required",
    "clearance is required",
    "must hold a clearance",
    "top secret",
    "ts sci",
    "secret clearance",
    "public trust",
    "dod clearance",
)
CITIZENSHIP_REQUIRED = (
    "citizenship required",
    "citizenship is required",
    "must be a us citizen",
    "must be a u s citizen",
    "us citizens only",
    "u s citizens only",
    "citizens only",
)
MANAGEMENT_TITLE_WORDS = {"director", "head", "vp", "svp", "evp", "president", "manager", "chief"}
MANAGEMENT_SIGNALS = (
    "direct reports",
    "manage a team",
    "managing a team",
    "lead a team",
    "leading a team",
    "build and lead",
    "people manager",
    "people management",
    "performance reviews",
    "hire and develop",
    "hiring and developing",
    "grow the team",
    "team of engineers",
)
INDIVIDUAL_SIGNALS = (
    "individual contributor",
    "hands on",
    "no direct reports",
    "without direct reports",
    "not a people manager",
)


def utc_day() -> date:
    return datetime.now(UTC).date()


def tokens(value: str) -> list[str]:
    return re.findall(r"[^\W_]+(?:[+#]+)?", unicodedata.normalize("NFKC", value).casefold())


def contains_phrase(haystack: list[str], needle: list[str]) -> bool:
    return bool(needle) and any(
        haystack[i : i + len(needle)] == needle for i in range(len(haystack) - len(needle) + 1)
    )


def work_modes(job) -> list[str]:
    words = tokens(f"{job.title} {job.location}")
    modes = []
    for mode, phrases in {
        "remote": ["remote"],
        "hybrid": ["hybrid"],
        "onsite": ["onsite", "on site"],
    }.items():
        if any(contains_phrase(words, tokens(phrase)) for phrase in phrases):
            negated = any(
                contains_phrase(words, tokens(f"{prefix} {phrase}"))
                for phrase in phrases
                for prefix in ("not", "no", "non", "not a", "not fully")
            )
            if not negated:
                modes.append(mode)
    return modes


def found(words: list[str], phrases) -> list[str]:
    return [phrase for phrase in phrases if contains_phrase(words, tokens(phrase))]


def eligibility(job, preferences) -> dict:
    """Geographic allowlist plus stated sponsorship, clearance and citizenship requirements."""
    from app.relevance import location_matches  # local import: relevance depends on scoring

    words = tokens(f"{job.title} {job.description}")
    evidence = []
    if preferences.locations:
        allowed = location_matches(job.location, preferences)
        evidence.append(
            f"Location label '{job.location}' {'matches' if allowed else 'is outside'} the "
            f"allowed phrases: {', '.join(preferences.locations)}"
        )
        geographic = 5 if allowed else 0
    else:
        evidence.append("No allowed location phrases configured; label not checked.")
        geographic = 5
    denied, offered = found(words, SPONSORSHIP_DENIED), found(words, SPONSORSHIP_OFFERED)
    needs_authorization = found(words, AUTHORIZATION_REQUIRED)
    clearance, citizenship = found(words, CLEARANCE_REQUIRED), found(words, CITIZENSHIP_REQUIRED)
    unmet = []
    if denied and not offered:
        evidence.append("Listing states sponsorship is not offered: " + ", ".join(denied))
        if preferences.needs_sponsorship:
            unmet.append("sponsorship")
    elif offered:
        evidence.append("Listing states sponsorship is offered: " + ", ".join(offered))
    elif needs_authorization:
        evidence.append(
            "Work authorization is required; the listing does not say whether sponsorship "
            "is offered."
        )
    if clearance:
        evidence.append("Clearance statement: " + ", ".join(clearance))
        if not preferences.has_clearance:
            unmet.append("clearance")
    if citizenship:
        evidence.append(
            "Citizenship statement, confirm eligibility yourself: " + ", ".join(citizenship)
        )
    if not (denied or offered or needs_authorization or clearance or citizenship):
        evidence.append("No sponsorship, clearance or citizenship statements detected.")
    if unmet:
        evidence.append("Unmet per your preferences: " + ", ".join(unmet))
    return {
        "key": "eligibility",
        "label": "Eligibility",
        "points": geographic + (0 if unmet else 5),
        "maximum": 10,
        "evidence": evidence,
    }


def responsibility(job, profile, preferences) -> dict:
    """People-management versus individual-contributor signals against the wanted level."""
    title_words = set(tokens(job.title))
    words = tokens(f"{job.title} {job.description}")
    management = sorted(title_words & MANAGEMENT_TITLE_WORDS) + found(words, MANAGEMENT_SIGNALS)
    individual = found(words, INDIVIDUAL_SIGNALS)
    level = (
        "mixed"
        if management and individual
        else "management"
        if management
        else "individual"
        if individual
        else "unknown"
    )
    wanted = preferences.responsibility
    if wanted == "auto":
        leads = [bool(set(tokens(t)) & MANAGEMENT_TITLE_WORDS) for t in profile.target_titles]
        wanted = (
            "any"
            if not leads or (any(leads) and not all(leads))
            else "management"
            if all(leads)
            else "individual"
        )
    if wanted == "any" or level == "mixed" or level == wanted:
        points = 5
    elif level == "unknown":
        points = 3
    else:
        points = 0
    signals = ", ".join(management + individual) or "none"
    return {
        "key": "responsibility",
        "label": "Responsibility level",
        "points": points,
        "maximum": 5,
        "evidence": [
            f"Listing signals: {level} ({signals})",
            f"Wanted: {wanted}"
            + (" (from target titles)" if preferences.responsibility == "auto" else ""),
        ],
    }


@dataclass(frozen=True)
class RatedJob:
    """A job the user marked "more like this" (+1) or "less like this" (-1)."""

    title: str
    company: str
    rating: int


RATING_POINTS = 15
# A rated job counts only when it shares at least a third of the title words.
RATING_SIMILARITY_FLOOR = 0.34
RATING_NEIGHBORS = 5
SAME_COMPANY_BONUS = 0.25


def title_words(title: str) -> frozenset[str]:
    return frozenset(word for word in tokens(title) if word not in TITLE_STOP_WORDS)


def rating_similarity(job, rated: RatedJob) -> float:
    """Title-word overlap (Jaccard), with a bonus when the employer is the same."""
    ours, theirs = title_words(job.title), title_words(rated.title)
    union = ours | theirs
    overlap = len(ours & theirs) / len(union) if union else 0.0
    company = normalize_company_name(job.company)
    same = bool(company) and company == normalize_company_name(rated.company)
    return min(1.0, overlap + (SAME_COMPANY_BONUS if same else 0.0))


def ratings_component(job, ratings) -> dict:
    """Up to ±15 points from the most similar rated jobs; explained by naming them.

    points = 15 × (similarity-weighted average of the ratings) × (best similarity),
    over the five most similar rated jobs at or above the similarity floor. A job
    you rated yourself is 100% similar to itself, so it moves the full 15 points.
    """
    near = sorted(
        ((rating_similarity(job, rated), rated) for rated in ratings),
        key=lambda pair: (-pair[0], pair[1].title, pair[1].company),
    )
    near = [pair for pair in near if pair[0] >= RATING_SIMILARITY_FLOOR][:RATING_NEIGHBORS]
    if not near:
        return {
            "key": "ratings",
            "label": "Your ratings",
            "points": 0,
            "maximum": RATING_POINTS,
            "evidence": [f"Not similar to any of the {len(ratings)} jobs you rated."],
        }
    weight = sum(similarity for similarity, _ in near)
    lean = sum(similarity * rated.rating for similarity, rated in near) / weight
    return {
        "key": "ratings",
        "label": "Your ratings",
        "points": round(RATING_POINTS * lean * near[0][0]),
        "maximum": RATING_POINTS,
        "evidence": [
            f"{'More' if rated.rating > 0 else 'Less'} like this: {rated.title} at"
            f" {rated.company} ({round(similarity * 100)}% similar)."
            for similarity, rated in near[:3]
        ],
    }


def cache_signature(job, profile, today: date, preferences=None, ratings=()) -> str:
    payload = {
        "version": VERSION,
        "day": today.isoformat(),
        "job": [job.title, job.description, job.location, job.posted_at.isoformat(), job.date_kind],
        "profile": [
            profile.skills,
            profile.target_titles,
            profile.location,
            profile.work_preferences,
        ],
        "preferences": preferences.model_dump() if preferences is not None else None,
        "ratings": sorted([rated.title, rated.company, rated.rating] for rated in ratings),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def score_job(job, profile, today: date, preferences=None, ratings=()) -> dict:
    if preferences is None:
        from app.relevance import MatchPreferences  # local import: relevance depends on scoring

        preferences = MatchPreferences()
    text_words = tokens(f"{job.title} {job.description}")
    skills = {tuple(tokens(skill)): skill for skill in profile.skills if tokens(skill)}
    matched_skills = [
        label for phrase, label in skills.items() if contains_phrase(text_words, list(phrase))
    ]
    skill_points = round(35 * len(matched_skills) / len(skills)) if skills else 0
    skill_evidence = (
        ["Matched: " + ", ".join(matched_skills)]
        if matched_skills
        else ["No saved skill phrases found in the title or description."]
    )
    missing = [label for label in skills.values() if label not in matched_skills]
    if missing:
        skill_evidence.append("Not found: " + ", ".join(missing))

    job_title = [word for word in tokens(job.title) if word not in TITLE_STOP_WORDS]
    title_points, title_evidence = 0, ["No target title words matched."]
    for target in profile.target_titles:
        target_words = [word for word in tokens(target) if word not in TITLE_STOP_WORDS]
        matched = sorted(set(target_words) & set(job_title))
        full = contains_phrase(job_title, target_words)
        points = (
            25
            if full
            else round(12.5 * len(matched) / len(set(target_words)))
            if target_words
            else 0
        )
        if points > title_points:
            title_points = points
            title_evidence = [
                f"Target: {target}",
                "Full target phrase matched."
                if full
                else "Partial title words: " + ", ".join(matched),
            ]

    location_match = contains_phrase(tokens(job.location), tokens(profile.location))
    modes = work_modes(job)
    preferred = sorted(set(modes) & set(profile.work_preferences))
    days = (today - job.posted_at.astimezone(UTC).date()).days
    recency = (
        0 if job.date_kind == "observed" else 5 if 0 <= days <= 7 else 2 if 7 < days <= 30 else 0
    )
    date_label = {"updated": "Updated", "observed": "Observed"}.get(job.date_kind, "Posted")
    components = [
        {
            "key": "skills",
            "label": "Skills",
            "points": skill_points,
            "maximum": 35,
            "evidence": skill_evidence,
        },
        {
            "key": "title",
            "label": "Target title",
            "points": title_points,
            "maximum": 25,
            "evidence": title_evidence,
        },
        {
            "key": "location",
            "label": "Location",
            "points": 10 if location_match else 0,
            "maximum": 10,
            "evidence": [
                f"Saved location phrase {'found' if location_match else 'not found'}: "
                f"{profile.location}"
            ],
        },
        {
            "key": "work_mode",
            "label": "Work preference",
            "points": 10 if preferred else 0,
            "maximum": 10,
            "evidence": [
                "Title/location labels: " + (", ".join(modes) or "unknown"),
                "Preferred matches: " + (", ".join(preferred) or "none"),
            ],
        },
        eligibility(job, preferences),
        responsibility(job, profile, preferences),
        {
            "key": "recency",
            "label": "Provider-date recency",
            "points": recency,
            "maximum": 5,
            "evidence": [
                f"{date_label} {job.posted_at.date().isoformat()}; {days} days before scoring date."
                if days >= 0
                else "Future provider date; no recency points."
            ],
        },
    ]
    if ratings:
        # Only once something is rated, so unrated scoring stays exactly as before.
        components.append(ratings_component(job, ratings))
    return {
        "total": max(0, min(100, sum(part["points"] for part in components))),
        "components": components,
        "version": VERSION,
        "as_of": today.isoformat(),
    }


def matches_filters(
    job,
    *,
    q: str,
    company: str,
    location: str,
    exclude: str,
    work_mode: str,
    min_score: int | None,
    max_age_days: int | None,
    today: date,
) -> bool:
    words = tokens(f"{job.title} {job.company} {job.location} {job.description}")
    if not set(tokens(q)).issubset(set(words)):
        return False
    if company.strip() and not contains_phrase(tokens(job.company), tokens(company)):
        return False
    if location.strip() and not contains_phrase(tokens(job.location), tokens(location)):
        return False
    if any(contains_phrase(words, tokens(term)) for term in exclude.split(",") if term.strip()):
        return False
    modes = work_modes(job)
    if work_mode == "unknown" and modes:
        return False
    if work_mode not in ("any", "unknown") and work_mode not in modes:
        return False
    if min_score is not None and (job.score is None or job.score < min_score):
        return False
    age = (today - job.posted_at.astimezone(UTC).date()).days
    if max_age_days is not None and not 0 <= age <= max_age_days:
        return False
    return True
