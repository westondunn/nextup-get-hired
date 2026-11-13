"""Local mail classification: synthetic subjects and bodies only, no network."""

# The public webmail and applicant-tracking domains in this file are intentional: mail
# detection keys on those exact domains, so a reserved example domain would not exercise
# it. Every local part, name and message body is synthetic.

from uuid import uuid4

import pytest

from app.application_detect import (
    AUTO_REPLY,
    CONFIRMATION,
    INTERVIEW,
    NONE,
    REJECTION,
    classify,
    split_sender,
)
from app.application_intake import _AUTOMATED_MAILBOX, match_pursuit
from app.models import Pursuit


@pytest.mark.parametrize(
    "subject,body,sender_name,sender_email,company,title,requisition,confidence",
    [
        (
            "Thank You for Applying to Acme - 10001 - Manager, Platform/ Systems Engineering",
            "We have received your application.",
            "acmecareers@people.acme.example",
            "acmecareers@people.acme.example",
            "Acme",
            "Manager, Platform/ Systems Engineering",
            "10001",
            "high",
        ),
        (
            "You have successfully submitted your Globex job application - 100002 - DevOps"
            " Engineer",
            "Dear Sam, thank you for applying to the role of DevOps Engineer - 100002 at Globex.",
            "Globex Talent Acquisition",
            "talent@globex.example",
            "Globex",
            "DevOps Engineer",
            "100002",
            "high",
        ),
        (
            "Thank you for applying",
            "We have received your application for the position of Director of Quality"
            " Engineering at Initech Corporation. Requisition ID: 1003",
            "Workday",
            "initech@myworkday.com",
            "Initech Corporation",
            "Director of Quality Engineering",
            "1003",
            "high",
        ),
        (
            "Thanks for applying to Hooli!",
            "We've received your application for Engineering Manager, Platform and will"
            " review it shortly.",
            "Hooli",
            "no-reply@hooli.example",
            "Hooli",
            "Engineering Manager, Platform",
            "",
            "high",
        ),
        (
            "Application received",
            "Thanks for applying! We will be in touch.",
            "",
            "no-reply@initech.example",
            "Initech",
            "",
            "",
            "medium",
        ),
        (
            "Sam, your application was sent to Initech",
            "Your application was sent to Initech",
            "LinkedIn",
            "jobs-noreply@linkedin.com",
            "Initech",
            "",
            "",
            "medium",
        ),
    ],
)
def test_confirmations_are_recognized_with_company_role_and_requisition(
    subject, body, sender_name, sender_email, company, title, requisition, confidence
):
    found = classify(subject, body, sender_name, sender_email)
    assert found.kind == CONFIRMATION
    assert (found.company, found.title, found.requisition, found.confidence) == (
        company,
        title,
        requisition,
        confidence,
    )
    assert found.evidence, "the matched phrase is kept for review"


@pytest.mark.parametrize(
    "subject,body",
    [
        (
            "Update on your application to Acme",
            "Thank you for applying to Acme. Unfortunately we are moving forward with other"
            " candidates.",
        ),
        ("Re: Resume (2026)", "Thank you for applying, here are next steps."),
        ("Fwd: Thank you for applying to Acme", "forwarded"),
        ("Your Phone Interview has been confirmed!", "Your interview is set."),
        ("New jobs for you: Director of QA", "Apply now to these roles."),
        ("Checking availability", "Can you talk Tuesday?"),
    ],
)
def test_rejections_conversations_and_alerts_are_not_confirmations(subject, body):
    assert classify(subject, body, "Acme", "no-reply@acme.example").kind != CONFIRMATION


@pytest.mark.parametrize(
    "subject,body,sender_name,sender_email,company,title",
    [
        (
            "Update on your application to Acme",
            "Thank you for applying to Acme. Unfortunately we are moving forward with other"
            " candidates.",
            "Acme",
            "no-reply@acme.example",
            "Acme",
            "",
        ),
        (
            "Your application for Director, QE at Globex",
            "After careful consideration we regret to inform you that we will not be moving"
            " forward with your candidacy.",
            "Globex Recruiting",
            "no-reply@globex.example",
            "Globex",
            "Director, QE",
        ),
        (
            "Re: Director role",
            "The client decided not to move forward with your candidacy. Sorry.",
            "Riley",
            "riley@initech.example",
            "Initech",
            "",
        ),
    ],
)
def test_rejections_are_recognized_even_inside_a_conversation(
    subject, body, sender_name, sender_email, company, title
):
    found = classify(subject, body, sender_name, sender_email)
    assert (found.kind, found.company, found.title) == (REJECTION, company, title)
    assert found.evidence


@pytest.mark.parametrize(
    "subject,body,sender_name,sender_email,company",
    [
        (
            "Your Phone Interview has been confirmed!",
            "Your interview is set.",
            "Acme Corporation @ icims",
            "acme+email+4@talent.icims.com",
            "Acme",
        ),
        (
            "checking availability for Acme interview",
            "Are you free Tuesday?",
            "Lee, Jordan",
            "jordan.lee@acme.example",
            "Acme",
        ),
        (
            "Next steps",
            "We would like to schedule a 30 minute phone screen with our recruiter.",
            "Riley",
            "riley@globex.example",
            "Globex",
        ),
    ],
)
def test_interview_invitations_name_the_employer_from_the_sender(
    subject, body, sender_name, sender_email, company
):
    found = classify(subject, body, sender_name, sender_email)
    assert (found.kind, found.company) == (INTERVIEW, company)


@pytest.mark.parametrize(
    "subject,body,sender_name,sender_email",
    [
        ("RE: Thank you - Platform Engineer Interview", "You are welcome.", "R", "r@acme.example"),
        ("5 interview tips", "Read our interview guide.", "Acme", "news@acme.example"),
        ("Interview invitation", "Apply now.", "LinkedIn", "jobs-noreply@linkedin.com"),
        ("Re: Resume (2026)", "Unfortunately I am out Tuesday; Wednesday?", "R", "r@acme.example"),
        ("Re: Lunch", "Could we schedule a quick interview prep chat?", "R", "r@acme.example"),
    ],
)
def test_thanks_advice_job_boards_and_small_talk_suggest_nothing(
    subject, body, sender_name, sender_email
):
    assert classify(subject, body, sender_name, sender_email).kind == NONE


def test_automatic_replies_are_flagged_by_subject_or_header():
    assert classify("Automatic reply: Follow-up", "Away", "R", "r@acme.example").kind == AUTO_REPLY
    assert classify("Out of Office: Follow-up", "", "R", "r@acme.example").kind == AUTO_REPLY
    flagged = classify("Follow-up", "Away until Monday", "R", "r@acme.example", auto_reply=True)
    assert flagged.kind == AUTO_REPLY
    assert classify("Follow-up", "Away until Monday", "R", "r@acme.example").kind == NONE


def pursuit(company, title, stage="review", requisition=None):
    job = {"company": company, "title": title}
    if requisition:
        job["requisition"] = requisition
    return Pursuit(id=uuid4(), job_key=str(uuid4()), job=job, stage=stage)


def test_match_pursuit_needs_the_same_employer_and_role():
    director = pursuit("Acme Robotics", "Director, Quality Engineering")
    manager = pursuit("Acme Robotics", "Senior Partner Solutions Manager")
    other = pursuit("Globex", "Director, Quality Engineering")
    rows = [manager, director, other]
    assert match_pursuit(rows, "Acme", "Director, Quality Engineering") is director
    assert match_pursuit(rows, "Acme Robotics", "director quality engineering") is director
    assert match_pursuit(rows, "Acme", "Director, Quality Engineering and Automation") is director
    assert match_pursuit(rows, "Acme", "DevOps Engineer") is None, "same employer, other role"
    assert match_pursuit(rows, "Initech", "Director, Quality Engineering") is None
    numbered = pursuit("Acme", "Renamed role", requisition="1004")
    assert match_pursuit([director, numbered], "Acme", "Director, QE", "1004") is numbered


@pytest.mark.parametrize(
    "address,automated",
    [
        ("no-reply@acme.example", True),
        ("acmecareerspeople@people.acme.example", True),
        ("talent@globex.example", True),
        ("acme+email+0000a@talent.icims.com", True),
        ("riley.jobson@acme.example", False),
        ("jordan.lee@acme.example", False),
    ],
)
def test_unmonitored_mailboxes_are_recognized(address, automated):
    assert bool(_AUTOMATED_MAILBOX.search(address)) is automated


def test_split_sender_reads_display_names_that_contain_an_address():
    assert split_sender("Riley Recruiter <Riley@Acme.example>") == (
        "Riley Recruiter",
        "riley@acme.example",
    )
    assert split_sender("careers@people.acme.example <careers@people.acme.example>") == (
        "careers@people.acme.example",
        "careers@people.acme.example",
    )
    assert split_sender("talent@acme.example") == ("", "talent@acme.example")
    assert split_sender("") == ("", "")
