"""Company normalization and the external classifier's matching predicate; no database."""

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.companies import company_matches, find_company_matches, normalize_company_name
from app.models import Company


@pytest.mark.parametrize(
    "raw,normalized",
    [
        ("Harlow Northwind", "harlow northwind"),
        ("The Harlow Northwind Corporation", "harlow northwind"),
        ("Harlow Northwind Corp.", "harlow northwind"),
        ("  ACME   Robotics, Inc. ", "acme robotics"),
        ("Smith-Jones Holdings Co., Ltd.", "smith jones holdings"),
        ("R.J. Marlowe Finch & Co.", "rj marlowe finch"),
        ("O'Fallowmere Media, LLC", "ofallowmere media"),
        ("Foo plc", "foo"),
        ("Tradeco Wholesale", "tradeco wholesale"),  # "co" only as a whole trailing word
        ("Theodore Labs", "theodore labs"),  # "the" only as a whole leading word
        ("Corporation Supply Company", "corporation supply company"),
        ("Inc", "inc"),  # stripping never empties a name
        ("The Co", "co"),
        ("Bélanor S.A.", "bélanor sa"),
        ("", ""),
        (None, ""),
    ],
)
def test_normalize_company_name(raw, normalized):
    assert normalize_company_name(raw) == normalized


@pytest.mark.parametrize(
    "names,expected",
    [
        ("Northwind", True),  # substring of the normalized name
        ("harlow northwind", True),
        ("  Harlow Northwind  ", True),  # trim() removes spaces
        ("HARLOW", True),
        ("Northwind Bank", False),
        ("Harlow Northwind Corporation", False),  # names from mail are not normalized
        ("Harry", True),  # alias, compared whole and case-insensitively
        ("harry n", False),
        ("No", False),  # shorter than three characters is ignored
        ("No|Initech|Northwind", True),  # any part of a pipe-delimited list
        ("Initech|Globex", False),
        ("", False),
        ("ha%nd", True),  # LIKE wildcards in the name behave as in PostgreSQL
        ("h_rlow", True),
        ("h\\_rlow", False),  # an escaped wildcard is literal
    ],
)
def test_company_matches_follows_the_labeler_query(names, expected):
    assert company_matches("harlow northwind", ["Harry", "HN Corp"], names) is expected


def test_find_company_matches_returns_every_candidate_that_matches():
    northwind = Company(id=uuid4(), name="Harlow Northwind", name_normalized="harlow northwind")
    northwind.aliases = ["Northwind"]
    bank = Company(id=uuid4(), name="Northwind Bank", name_normalized="northwind bank", aliases=[])
    other = Company(id=uuid4(), name="Initech", name_normalized="initech", aliases=[])
    session = MagicMock()
    session.scalars.return_value.all.return_value = [northwind, bank, other]
    assert find_company_matches(session, ["Northwind"]) == [northwind, bank]
    assert find_company_matches(session, ["xy", "Initech Inc"]) == []
    assert find_company_matches(session, ["Initech", "Globex"]) == [other]
    statement = str(session.scalars.call_args[0][0])
    assert "companies.status !=" in statement, "archived companies are never candidates"


def test_open_company_index_matches_employers_by_normalized_name_and_alias():
    from app.companies import OpenCompanyIndex
    from app.models import Pursuit

    northwind = Company(id=uuid4(), name="Harlow Northwind", name_normalized="harlow northwind")
    northwind.aliases = ["Northwind"]

    def pursuit(company, title, stage="applied", key=None, record=None):
        row = Pursuit(
            id=uuid4(), job_key=key or title, job={"company": company, "title": title}, stage=stage
        )
        row.company = record
        return row

    index = OpenCompanyIndex(
        [
            pursuit("Harlow Northwind Corp.", "Platform Engineer", key="k1", record=northwind),
            pursuit("Acme Robotics, Inc.", "Director QE", stage="review", key="k2"),
            pursuit("Company not provided", "Mystery role", key="k3"),
        ]
    )
    assert [e.title for e in index.lookup("The Harlow Northwind Corporation")] == [
        "Platform Engineer"
    ]
    assert [e.title for e in index.lookup("northwind")] == ["Platform Engineer"], "alias"
    assert [e.stage for e in index.lookup("ACME Robotics")] == ["review"]
    assert index.lookup("Globex") == [] and index.lookup("Company not provided") == []
    assert index.others("Acme Robotics", "k2") == [], "the job itself is not a conflict"
    assert [e.title for e in index.others("Acme Robotics", "other")] == ["Director QE"]
