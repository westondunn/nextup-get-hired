"""Canonical companies: normalization, upsert-and-link, status, and name matching.

``companies.name_normalized`` is computed in PostgreSQL by ``nextup_normalize_company``
(migration 0027), so the database stays the single source of truth even for rows the
application never writes. ``normalize_company_name`` mirrors it for code and tests;
an integration test keeps the two in step.

``find_company_matches`` implements the exact predicate of the query an external email
labeler runs against this table (see docs/CORRESPONDENCE_SYNC.md).
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, selectinload

from app.models import Company, Contact, Pursuit

# Statuses the user chooses; the derived rule never overwrites them.
USER_STATUSES = ("interviewing", "archived")
# Adzuna's stand-in for a missing employer; never a company (see job_identity.py).
PLACEHOLDERS = frozenset({"company not provided"})
MIN_QUERY_CHARS = 3

_DROPPED = re.compile(r"['’.]")
_PUNCTUATION = re.compile(r"[^\w\s]|_")
_SPACES = re.compile(r"\s+")
_LEADING_THE = re.compile(r"^the ")
_SUFFIXES = re.compile(r"( (inc|llc|corp|corporation|co|ltd|plc))+$")


def normalize_company_name(value: str | None) -> str:
    """Python mirror of the SQL function ``nextup_normalize_company``.

    lower → drop apostrophes and full stops → other punctuation becomes a space →
    collapse spaces → strip a leading "the" and trailing corporate suffixes, unless
    that would leave nothing. "The Harlow Northwind Corp." → "harlow northwind".
    """
    cleaned = _SPACES.sub(" ", _PUNCTUATION.sub(" ", _DROPPED.sub("", (value or "").lower())))
    cleaned = cleaned.strip(" ")
    stripped = _SUFFIXES.sub("", _LEADING_THE.sub("", cleaned, count=1)).strip(" ")
    return stripped or cleaned


# ---------- Upsert and link ----------


def _by_alias(session: Session, name: str) -> Company | None:
    return session.scalar(
        select(Company)
        .where(text("lower(:name) = ANY (SELECT lower(a) FROM unnest(companies.aliases) a)"))
        .params(name=name)
        .order_by(Company.name)
        .limit(1)
    )


def upsert_company(session: Session, name: str | None, now: datetime | None = None):
    """The company this name refers to, created when none matches. None for no name.

    Matches the normalized name first, then an alias, so "KVL Partners" finds "KVL"
    once that alias has been recorded.
    """
    name = (name or "").strip()
    if not name:
        return None
    normalized = session.scalar(select(func.nextup_normalize_company(name)))
    if not normalized or normalized in PLACEHOLDERS:
        return None
    found = session.scalar(select(Company).where(Company.name_normalized == normalized))
    if found is None:
        found = _by_alias(session, name)
    if found is not None:
        return found
    now = now or datetime.now(UTC)
    company_id = session.scalar(
        insert(Company)
        .values(id=uuid4(), name=name[:500], created_at=now, updated_at=now)
        .on_conflict_do_nothing(index_elements=["name_normalized"])
        .returning(Company.id)
    )
    if company_id is None:  # another transaction created it first
        return session.scalar(select(Company).where(Company.name_normalized == normalized))
    return session.get(Company, company_id)


def refresh_status(session: Session, company_id: UUID | None) -> None:
    """Derive the status from linked rows, exactly as migration 0027's backfill does.

    applied: a linked pursuit has applied_at · contact_only: only contacts are linked ·
    otherwise tracking. A status the user set (interviewing, archived) is kept.
    """
    if company_id is None:
        return
    company = session.get(Company, company_id)
    if company is None or company.status in USER_STATUSES:
        return

    def count(model, *conditions) -> int:
        return session.scalar(
            select(func.count())
            .select_from(model)
            .where(model.company_id == company_id, *conditions)
        )

    if count(Pursuit, Pursuit.applied_at.is_not(None)):
        status = "applied"
    elif not count(Pursuit) and count(Contact):
        status = "contact_only"
    else:
        status = "tracking"
    if company.status != status:
        company.status = status
        company.updated_at = datetime.now(UTC)


def _relink(session: Session, row, name: str | None, now: datetime | None) -> Company | None:
    previous = row.company_id
    company = upsert_company(session, name, now)
    row.company_id = company.id if company else None
    session.flush()
    for company_id in {previous, row.company_id} - {None}:
        refresh_status(session, company_id)
    return company


def link_pursuit(session: Session, pursuit: Pursuit, now: datetime | None = None):
    """Link a pursuit to its employer's company and refresh that company's status."""
    return _relink(session, pursuit, str((pursuit.job or {}).get("company") or ""), now)


def link_contact(session: Session, contact: Contact, now: datetime | None = None):
    """Link a contact to its employer's company and refresh that company's status."""
    return _relink(session, contact, contact.company, now)


# ---------- Open applications by employer ----------

# A submitted application that has not been decided. Jobs still in review or preparing
# are only being considered and hold nothing; accepted, rejected, withdrawn and
# dismissed release the employer.
OPEN_STAGES = ("applied", "interview", "offer")


@dataclass(frozen=True)
class OpenApplication:
    pursuit_id: UUID
    title: str
    company: str
    stage: str
    job_key: str


class OpenCompanyIndex:
    """Which employers have an open application, matched by normalized name or alias.

    Built from current pursuits on every request, so an application that closes
    releases its employer immediately; nothing is stored.
    """

    def __init__(self, pursuits: Iterable[Pursuit]):
        self._by_key: dict[str, list[OpenApplication]] = {}
        for pursuit in pursuits:
            job = pursuit.job or {}
            entry = OpenApplication(
                pursuit_id=pursuit.id,
                title=str(job.get("title", "")),
                company=str(job.get("company", "")),
                stage=pursuit.stage,
                job_key=pursuit.job_key,
            )
            names = {entry.company}
            if pursuit.company is not None:
                names.add(pursuit.company.name)
                names.update(pursuit.company.aliases or [])
            for key in {normalize_company_name(name) for name in names}:
                if key and key not in PLACEHOLDERS:
                    self._by_key.setdefault(key, []).append(entry)

    def lookup(self, company: str | None) -> list[OpenApplication]:
        return list(self._by_key.get(normalize_company_name(company), []))

    def others(self, company: str | None, job_key: str) -> list[OpenApplication]:
        """Open applications at this employer for a different job than ``job_key``."""
        return [entry for entry in self.lookup(company) if entry.job_key != job_key]


def open_company_index(session: Session) -> OpenCompanyIndex:
    return OpenCompanyIndex(
        session.scalars(
            select(Pursuit)
            .where(Pursuit.stage.in_(OPEN_STAGES))
            .options(selectinload(Pursuit.company))
            .order_by(Pursuit.created_at)
        ).all()
    )


# ---------- Matching (the external classifier's predicate) ----------


def _like_regex(pattern: str) -> re.Pattern:
    """PostgreSQL LIKE semantics: % any run, _ any one character, backslash escapes."""
    parts, index = [], 0
    while index < len(pattern):
        char = pattern[index]
        if char == "\\" and index + 1 < len(pattern):
            parts.append(re.escape(pattern[index + 1]))
            index += 2
            continue
        parts.append(".*" if char == "%" else "." if char == "_" else re.escape(char))
        index += 1
    return re.compile("".join(parts), re.DOTALL | re.IGNORECASE)


def company_matches(name_normalized: str, aliases: Iterable[str], names: str) -> bool:
    """True when one pipe-delimited name matches, as the labeler's SQL decides it.

    For each part q with length(trim(q)) >= 3: name_normalized ILIKE '%' ||
    lower(trim(q)) || '%', or lower(trim(q)) equals a lower-cased alias. PostgreSQL's
    trim() removes spaces only, and q is not normalized, so "Acme Inc" does not
    match a company normalized to "acme" unless "Acme Inc" is an alias.
    """
    lowered_aliases = {alias.lower() for alias in aliases}
    for part in names.split("|"):
        query = part.strip(" ")
        if len(query) < MIN_QUERY_CHARS:
            continue
        query = query.lower()
        if _like_regex(f"%{query}%").fullmatch(name_normalized) or query in lowered_aliases:
            return True
    return False


def find_company_matches(session: Session, names: list[str]) -> list[Company]:
    """Every non-archived company the labeler's query would accept for these names.

    The classifier's query stops at LIMIT 1 with no ORDER BY; this returns all matches,
    ordered by name, so a caller can see when a name is ambiguous.
    """
    joined = "|".join(names)
    candidates = session.scalars(
        select(Company).where(Company.status != "archived").order_by(Company.name, Company.id)
    ).all()
    return [c for c in candidates if company_matches(c.name_normalized, c.aliases, joined)]
