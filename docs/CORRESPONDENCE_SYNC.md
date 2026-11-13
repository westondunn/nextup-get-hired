# Optional external email classifier

NextUp can accept classification hints for imported mail from a separate program that you run yourself. This document is the contract between NextUp and such a program.

**The feature is optional and off by default.** NextUp does not include a classifier, does not need one, and every shipped configuration sets `NEXTUP_EXTERNAL_CLASSIFIER_ENABLED` to `false`. There is currently no supported way to switch it on; this page describes the interface so that the code and the database schema can be understood.

## What it does

NextUp's read-only mail sync imports messages into the `communications` table and runs its own rule-based detection on them. An external classifier may add a second opinion:

1. The classifier writes one row per mail message into the table `email_classifications`.
2. After each mail sync run, NextUp merges every unapplied row whose message has been imported into that message's `detection` field, as a hint, and stamps the row's `applied_at`.

NextUp's own detection stays authoritative. A hint never changes the detected kind, the message status, or any existing link to an application or a contact. The only field a hint may fill is an empty suggested application, taken from the matched company. Where the hint and NextUp's detection disagree, the disagreement is recorded with the hint.

The classifier never writes `communications`. It has write access to `email_classifications` only.

## The table

| Column | Type | Meaning |
|---|---|---|
| `gmail_message_id` | text, primary key | The provider's message identifier; must equal the identifier NextUp stores for the imported message |
| `thread_id` | text, optional | The provider's thread identifier |
| `classification` | text | One of `new_application`, `opportunity`, `existing_company`, `not_relevant` |
| `companies` | text array | Company names the classifier found; empty when none |
| `company_id` | UUID, optional | A row of `companies` that the classifier matched |
| `confidence` | number from 0 to 1, optional | Three decimal places |
| `model` | text, optional | Free-text label of the model used |
| `prompt_version` | text, optional | Free-text label of the prompt or rule set used |
| `classified_at` | timestamp | Set by the database |
| `applied_at` | timestamp, optional | Set by NextUp when the hint has been merged. The classifier must only ever set it to `NULL` |

## Writing a classification

The classifier uses exactly this statement. Parameters are text; an empty string stands for "no value" in parameters 4 and 5, and parameter 4 is a list of company names separated by `|`.

```sql
INSERT INTO email_classifications
  (gmail_message_id, thread_id, classification, companies, company_id, confidence, model, prompt_version)
VALUES ($1, $2, $3, string_to_array(NULLIF($4, ''), '|'), NULLIF($5, '')::uuid, $6::numeric, $7, $8)
ON CONFLICT (gmail_message_id) DO UPDATE SET
  thread_id = EXCLUDED.thread_id, classification = EXCLUDED.classification,
  companies = EXCLUDED.companies, company_id = EXCLUDED.company_id,
  confidence = EXCLUDED.confidence, model = EXCLUDED.model,
  prompt_version = EXCLUDED.prompt_version, classified_at = now(), applied_at = NULL;
```

Consequences of this statement:

- Writing a message a second time replaces the earlier classification and clears `applied_at`, so NextUp applies the new hint on its next sync run.
- A classification written before the message is imported is applied in the run that imports it. One written afterwards is applied on the following run.
- When no company was found, the statement passes `NULL` for `companies`; a database trigger stores an empty array instead.

## Matching a company

A classifier that wants to fill `company_id` looks the name up in the `companies` table. For each candidate name `q` of at least three characters after trimming spaces, a company that is not archived matches when its `name_normalized` contains `lower(trim(q))`, or when `lower(trim(q))` equals one of its aliases compared in lower case. The candidate name is not normalised first, so a legal suffix such as "Inc" prevents a match unless that spelling is stored as an alias.

`find_company_matches` in `backend/app/companies.py` implements the same rule in Python, and the tests keep the two in step.

## Database access

The classifier connects with its own database login, which you create and manage yourself. NextUp never creates it.

- The login's name is fixed by migration `0029`; it is the value of `CLASSIFIER_ROLE` in `backend/app/guard/facts.py`.
- If a login of that name already exists when migration `0029` runs, the migration grants it `SELECT`, `INSERT` and `UPDATE` on `email_classifications`. If it does not exist, nothing is granted.
- The migration guard checks this. While `NEXTUP_EXTERNAL_CLASSIFIER_ENABLED` is `false`, the guard refuses to migrate a database in which that login exists or in which any login other than NextUp's own holds privileges on NextUp's tables. A default installation therefore never grants anything to an outside login.

## Removing it

Rolling migration `0029` back removes the table and deletes the merged hints from the imported messages. NextUp's own detection results are kept.
