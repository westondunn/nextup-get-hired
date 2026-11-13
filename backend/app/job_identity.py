"""Conservative grouping keys; raw source records are never collapsed or deleted."""

import hashlib
import json
import unicodedata


def identity_key(source: str, external_id: str, company: str, title: str, location: str) -> str:
    def normalized(value):
        return " ".join(unicodedata.normalize("NFKC", value).casefold().split())

    parts = [normalized(value) for value in (company, title, location)]
    if not all(parts) or parts[0] == "company not provided":
        parts = [source, external_id]
    return hashlib.sha256(json.dumps(["live", *parts], ensure_ascii=False).encode()).hexdigest()
