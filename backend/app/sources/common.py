from html.parser import HTMLParser
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import AwareDatetime, BaseModel, Field, StringConstraints, field_validator


class SourceError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def require_live_requests(settings) -> None:
    """Chokepoint for every live provider request.

    Called first by each provider entry point, before any HTTP client is created or used,
    including injected clients. In fixture data mode no external request is ever made:
    job sources are served from the bundled synthetic fixtures (app.job_tasks), and every
    other provider path refuses here.
    """
    if getattr(settings, "fixture_data_mode", False):
        raise SourceError(
            "fixture_mode", "Live provider requests are disabled in fixture data mode."
        )


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def plain_text(value: str) -> str:
    parser = PlainText()
    parser.feed(value)
    return " ".join(" ".join(parser.parts).replace("\x00", "").split())


CleanString = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, pattern=r"^[^\x00]+$")
]


class NormalizedJob(BaseModel):
    external_id: CleanString = Field(max_length=200)
    title: CleanString = Field(max_length=500)
    company: CleanString = Field(max_length=300)
    location: CleanString = Field(max_length=500)
    description: str = Field(max_length=20000)
    url: str = Field(max_length=2048)
    posted_at: AwareDatetime
    date_kind: Literal["posted", "updated", "observed"] = "posted"

    @field_validator("url")
    @classmethod
    def safe_url(cls, value):
        parsed = urlsplit(value)
        if (
            parsed.scheme not in ("http", "https")
            or not parsed.hostname
            or parsed.username
            or parsed.password
        ):
            raise ValueError("Expected an HTTP(S) listing URL without credentials")
        if any(ord(char) < 32 for char in value):
            raise ValueError("Invalid URL characters")
        return value
