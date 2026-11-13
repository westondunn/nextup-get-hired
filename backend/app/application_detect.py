"""Deterministic, local classification of imported mail. No network, no AI.

Recognizes employer application confirmations ("Thank you for applying to ..."),
rejections, interview invitations and automatic replies, and extracts the company,
role and requisition they name. Every result quotes the text it matched so the
decision can be reviewed.
"""

import re
from dataclasses import asdict, dataclass

CONFIRMATION = "application_confirmation"
AUTO_REPLY = "auto_reply"
REJECTION = "rejection"
INTERVIEW = "interview_invitation"
NONE = "none"
# Automated mail that is not an employer's response to you.
NOT_A_REPLY = (CONFIRMATION, AUTO_REPLY)
# Mail that does not wait for your answer (a rejection is a response, but needs none).
NO_ANSWER_NEEDED = (CONFIRMATION, AUTO_REPLY, REJECTION)
# The pursuit stage a kind of mail points to; always confirmed by the user.
STAGE_FOR_KIND = {REJECTION: "rejected", INTERVIEW: "interview"}
# Bump when the rules change so stored mail classified as "none" is looked at again.
VERSION = 2

BODY_SCAN_CHARS = 6000

_AUTO_REPLY = re.compile(
    r"^\s*(automatic reply|auto[- ]?reply|autoreply|out of (the )?office|ooo)\b[:\s-]", re.I
)
_FORWARD_OR_REPLY = re.compile(r"^\s*(re|fw|fwd)\s*:", re.I)
_CONFIRM = re.compile(
    r"thank(?:s| you) for (?:applying|your application|submitting your application)"
    r"|thank(?:s| you) for your interest in (?:the|our|joining|a career)"
    r"|(?:successfully )?(?:submitted|received|completed) your (?:[\w&.'-]+ ){0,4}application"
    r"|your (?:[\w&.'-]+ ){0,4}application (?:has been|was|is) "
    r"(?:successfully )?(?:received|submitted|sent)"
    r"|application (?:received|submitted|confirmation|complete)"
    r"|we(?:'ve| have)? (?:successfully )?received your (?:[\w&.'-]+ ){0,4}application"
    r"|your application (?:for|to)\b",
    re.I,
)
# A confirmation phrase followed by a decision is a rejection, not a new application.
_DECLINE = re.compile(
    r"unfortunately|regret to inform|not (?:be )?(?:moving|proceeding|going) forward"
    r"|other candidates|decided not to|will not be (?:moving|proceeding)"
    r"|position has been filled|no longer (?:under consideration|being considered)"
    r"|not been selected|pursue other (?:applicants|candidates)",
    re.I,
)
# Unambiguous decisions; a bare "unfortunately" in a conversation is not one.
_REJECT = re.compile(
    r"regret to inform|not (?:be )?(?:moving|proceeding|going) forward"
    r"|(?:move|moving|proceed|proceeding|go|going) (?:forward |ahead )?with (?:other|another)"
    r"|decided not to (?:move|proceed|pursue|continue)|will not be (?:moving|proceeding)"
    r"|position has been filled|no longer (?:under consideration|being considered)"
    r"|not been selected|not selected (?:for|to)|pursue other (?:applicants|candidates)"
    r"|unable to (?:offer you|move forward|proceed with your)",
    re.I,
)
_REJECT_CONTEXT = re.compile(
    r"application|applying|applied|candidacy|candidate|position|role|interview", re.I
)
_INTERVIEW_SUBJECT = re.compile(
    r"\binterviews?\b|\b(?:phone|recruiter|technical|hiring manager) screen", re.I
)
# Thank-you notes and advice articles mention interviews without inviting you to one.
_THANKS = re.compile(
    r"\bthank(?:s| you)\b|\b(?:tips?|guide|advice|questions|how to|webinar|newsletter)\b", re.I
)
_INTERVIEW_BODY = re.compile(
    r"(?:schedule|set up|arrange|book|invite you (?:to|for)) (?:an? |your |the )?"
    r"(?:[\w-]+ ){0,2}(?:interview|phone screen)"
    r"|interview (?:has been|is) (?:scheduled|confirmed)"
    r"|availability for (?:an? |the |your )?(?:[\w-]+ ){0,2}(?:interview|phone screen)",
    re.I,
)
_REQUISITION = re.compile(
    r"^(?:req(?:uisition)?\.?\s*(?:id)?\s*[#:]?\s*)?([A-Z]{0,4}[-_]?\d{3,})$", re.I
)
_END = r"(?=\s+-\s|\s+\|\s|[!:.,;(\n]|\s+(?:and|for|as|has|was|is|we|your|a member)\b|$)"
# Up to four capitalized words; a full stop only counts inside a word (Acme.io, not "Acme.").
_WORD = r"[A-Z](?:[\w&'-]|\.(?=\w))*"
_NAME = _WORD + "(?: " + _WORD + "){0,3}"
_COMPANY_PATTERNS = [
    re.compile(r"application (?:was|has been) sent to (?P<v>[A-Z].+?)" + _END),
    re.compile(
        r"(?:role|position|job) of [^.\n]{2,120}? at "
        "(?P<v>" + _NAME + ")"
    ),
    re.compile("your (?P<v>" + _NAME + ") (?:job )?application"),
    re.compile(
        r"appl(?:ying|ication|ied) (?:to|at|with) (?!the |our |a |an |this )(?P<v>.+?)" + _END, re.I
    ),
    re.compile(
        r"interest in (?:joining |working at |a career (?:at|with) )(?P<v>.+?)" + _END, re.I
    ),
    re.compile(r"(?:role|position|opening|job) (?:at|with) (?P<v>[A-Z].+?)" + _END),
    re.compile(r"\d\s+at (?P<v>" + _NAME + ")" + _END),
    re.compile(r"interest in (?!the |our |a |an |this |joining |working )(?P<v>[A-Z].+?)" + _END),
]
_TITLE_PATTERNS = [
    re.compile(
        r"(?:for|to) (?:the|our) (?:role|position|job|opening) of (?P<v>.+?)"
        r"(?=\s+-\s+\d|\s+(?:with|at|in)\b|[.,;!(\n]|$)",
        re.I,
    ),
    re.compile(
        r"(?:application|applying|applied|interest) (?:for|to|in) (?:the|our) "
        r"(?P<v>.+?) (?:role|position|opening|job|opportunity)\b",
        re.I,
    ),
    re.compile(r"(?:position|role|job title|job)\s*:\s*(?P<v>[^\n.;!]+)", re.I),
    re.compile(
        r"application for (?!the |our |a |an |this )(?P<v>[A-Z].+?)"
        r"(?=\s+(?:at|with|and|we|has|was|is)\b|[.;!(\n]|$)"
    ),
]
_SENDER_NOISE = re.compile(
    r"\b(talent acquisition|talent|recruiting|recruitment|recruiters?|careers?|hiring team"
    r"|hiring|jobs?|team|hr|human resources|no[- ]?reply|notifications?|workday|icims"
    r"|corporation|corp|inc|llc|ltd)\b\.?",
    re.I,
)
_JOB_BOARD = re.compile(
    r"linkedin|indeed|glassdoor|ziprecruiter|dice|monster|greenhouse|lever|ashby|smartrecruiters"
    r"|jobvite|taleo|successfactors|myworkday|workday|icims",
    re.I,
)


@dataclass(frozen=True)
class Detection:
    kind: str = NONE
    confidence: str = ""
    company: str = ""
    title: str = ""
    requisition: str = ""
    evidence: str = ""

    def as_dict(self) -> dict:
        return {"v": VERSION, **{key: value for key, value in asdict(self).items() if value}}


def split_sender(value: str) -> tuple[str, str]:
    """(display name, lowercase address) from a stored ``Name <address>`` sender.

    ``email.utils.parseaddr`` rejects a display name that itself contains "@", which
    some applicant-tracking mailers send, so the angle-bracket form is read directly.
    """
    value = (value or "").strip()
    found = re.search(r"<([^<>\s]+@[^<>\s]+)>\s*$", value)
    if found:
        return value[: found.start()].strip(" \t\"'"), found.group(1).lower()
    found = re.search(r"[^\s<>\"',;]+@[^\s<>\"',;]+", value)
    return ("", found.group(0).lower()) if found else (value, "")


def _clean(value: str, limit: int = 200) -> str:
    value = re.sub(r"\s+", " ", value).strip(" \t-–—|:;,.!\"'")
    return value[:limit].strip()


def _first(patterns, *texts: str) -> str:
    for text in texts:
        for pattern in patterns:
            found = pattern.search(text)
            if found and 2 <= len(_clean(found.group("v"))) <= 120:
                return _clean(found.group("v"))
    return ""


def _from_subject_segments(subject: str) -> tuple[str, str]:
    """Split "Thank you for applying to Acme - 10001 - Director, QE" into its parts."""
    title = requisition = ""
    for segment in [_clean(part) for part in re.split(r"\s+[-–—|]\s+", subject)][1:]:
        match = _REQUISITION.match(segment)
        if match:
            requisition = requisition or match.group(1)
        elif len(segment) >= 3 and not _CONFIRM.search(segment):
            title = segment  # the last descriptive segment names the role
    return title, requisition


def _company_from_sender(sender_name: str, sender_email: str) -> str:
    name = sender_name if "@" not in sender_name else sender_name.split("@", 1)[0]
    name = _clean(_SENDER_NOISE.sub(" ", name))
    if _JOB_BOARD.fullmatch(name):
        return ""  # a job board or applicant-tracking system is not the employer
    if len(name) >= 2 and not re.fullmatch(r"[a-z0-9._-]+", name):
        return name
    from app.correspondence_tasks import _domain_label

    label = _domain_label(sender_email)
    return (label.upper() if len(label) <= 3 else label.capitalize()) if label else ""


def _employer_of_sender(sender_name: str, sender_email: str) -> str:
    """For mail a person writes, the domain names the employer better than their name."""
    from app.correspondence_tasks import _domain_label

    label = _domain_label(sender_email)
    if label:
        return label.upper() if len(label) <= 3 else label.capitalize()
    return "" if "," in sender_name else _company_from_sender(sender_name, "")


def _named(subject: str, text: str, sender_name: str, sender_email: str) -> tuple[str, str, str]:
    """(company, role, requisition) as far as the message names them."""
    title, requisition = _from_subject_segments(subject)
    lead = re.split(r"\s+[-–—|]\s+", subject)[0]
    company = _first(_COMPANY_PATTERNS, lead, text) or _company_from_sender(
        sender_name, sender_email
    )
    title = title or _first(_TITLE_PATTERNS, subject, text)
    if not requisition:
        numbered = re.search(
            r"(?:req(?:uisition)?|job)\s*(?:id|number|#)?\s*[#:]?\s*(\d{3,})", text, re.I
        )
        requisition = numbered.group(1) if numbered else ""
    return company, title, requisition[:60]


def classify(
    subject: str,
    body: str,
    sender_name: str = "",
    sender_email: str = "",
    auto_reply: bool = False,
) -> Detection:
    subject = re.sub(r"\s+", " ", subject or "").strip()
    if auto_reply or _AUTO_REPLY.match(subject):
        return Detection(kind=AUTO_REPLY, evidence=subject[:200])
    text = re.sub(r"\s+", " ", (body or "")[:BODY_SCAN_CHARS])
    conversation = bool(_FORWARD_OR_REPLY.match(subject))
    bare_subject = _FORWARD_OR_REPLY.sub("", subject).strip()

    rejected = _REJECT.search(subject) or _REJECT.search(text)
    if rejected and _REJECT_CONTEXT.search(f"{subject} {text}"):
        company, title, requisition = _named(bare_subject, text, "", "")
        company = company or _employer_of_sender(sender_name, sender_email)
        if _CONFIRM.search(title) or _REJECT.search(title):
            title = ""
        return Detection(
            kind=REJECTION,
            company=company,
            title=title,
            requisition=requisition,
            evidence=_clean(rejected.group(0)),
        )

    invited = None
    if not _THANKS.search(subject):
        board = _JOB_BOARD.fullmatch(_clean(_SENDER_NOISE.sub(" ", sender_name)))
        invited = (None if board else _INTERVIEW_SUBJECT.search(subject)) or (
            None if conversation else _INTERVIEW_BODY.search(text)
        )
    if invited:
        # Interview mail rarely names the employer in a fixed phrase; the sender does.
        return Detection(
            kind=INTERVIEW,
            company=_employer_of_sender(sender_name, sender_email),
            evidence=_clean(invited.group(0)),
        )

    if conversation:
        return Detection()  # a conversation, not an automated confirmation
    found = _CONFIRM.search(subject) or _CONFIRM.search(text)
    if not found or _DECLINE.search(subject) or _DECLINE.search(text):
        return Detection()
    company, title, requisition = _named(subject, text, sender_name, sender_email)
    return Detection(
        kind=CONFIRMATION,
        confidence="high" if company and title else "medium",
        company=company,
        title=title,
        requisition=requisition,
        evidence=_clean(found.group(0)),
    )
