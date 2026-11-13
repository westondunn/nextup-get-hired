"""Agreement between Nextup's own detection and the external classifier; no database."""

import pytest

from app.email_classifications import agrees


@pytest.mark.parametrize(
    "kind,classification,expected",
    [
        ("application_confirmation", "new_application", True),
        ("rejection", "new_application", True),
        ("interview_invitation", "opportunity", True),
        ("application_confirmation", "not_relevant", False),
        ("interview_invitation", "new_application", False),
        ("rejection", "existing_company", False),
        ("none", "opportunity", None),  # Nextup has no opinion: never a disagreement
        ("auto_reply", "not_relevant", None),
        (None, "new_application", None),
    ],
)
def test_nextup_detection_decides_and_only_its_opinions_can_disagree(
    kind, classification, expected
):
    assert agrees(kind, classification) is expected


def test_the_api_returns_the_hint_under_a_neutral_key():
    from app.contacts import _detection_out
    from app.email_classifications import HINT_KEY

    hint = {"classification": "opportunity", "agrees": None}
    stored = {"kind": "none", "v": 3, HINT_KEY: hint}
    assert _detection_out(stored) == {"kind": "none", "v": 3, "classifier": hint}
    assert HINT_KEY in stored, "the stored value is not modified"
    assert _detection_out({"kind": "none"}) == {"kind": "none"}
    assert _detection_out(None) is None
