"""The maintainer planning pack has complete, deterministic prompt metadata."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import check_planning_pack

REPO = Path(__file__).resolve().parents[2]
COMMIT = "f9024aacbfead69bf9afafa93877b9a001f7a59a"


def prompt(
    *,
    work_id="proposed-sample",
    status="proposed",
    issue="pending",
    primary_model="gpt-6.2-astra",
    validation_model="none",
    commit=COMMIT,
    canonical_sources="issue-draft",
    depends_on="none",
):
    metadata = {
        "work_id": work_id,
        "status": status,
        "issue": issue,
        "primary_model": primary_model,
        "reasoning_effort": "ultra",
        "validation_model": validation_model,
        "depends_on": depends_on,
        "approval_gates": "full-verification",
        "canonical_sources": canonical_sources,
        "last_reviewed_commit": commit,
    }
    frontmatter = "\n".join(f"{key}: {value}" for key, value in metadata.items())
    sections = "\n\n".join(
        f"## {section}\n\nComplete content."
        for section in check_planning_pack.REQUIRED_PROMPT_SECTIONS
    )
    return f"---\n{frontmatter}\n---\n\n# Sample prompt\n\n{sections}\n"


def issue_draft(*, omit=None):
    sections = [
        section for section in check_planning_pack.REQUIRED_ISSUE_SECTIONS if section != omit
    ]
    return (
        "# Draft issue\n\n"
        + "\n\n".join(f"## {section}\n\nComplete content." for section in sections)
        + "\n"
    )


class PlanningPack(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def write(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def test_absent_directories_are_an_empty_valid_pack(self):
        self.assertEqual(check_planning_pack.validate(self.root), [])
        errors = "\n".join(check_planning_pack.validate(self.root, require_pack=True))
        self.assertIn("required planning-pack file is missing", errors)
        self.assertIn("required prompt directory is missing or empty", errors)

    def test_valid_prompt_and_matching_issue_draft(self):
        self.write("docs/prompts/proposed/sample.md", prompt())
        self.write("docs/planning/issue-drafts/sample.md", issue_draft())
        self.assertEqual(check_planning_pack.validate(self.root), [])

    def test_missing_metadata_and_prompt_section_are_reported(self):
        text = (
            prompt()
            .replace("primary_model: gpt-6.2-astra\n", "")
            .replace("## Stop conditions", "## Ending")
        )
        self.write("docs/prompts/proposed/sample.md", text)
        errors = "\n".join(check_planning_pack.validate(self.root))
        self.assertIn("missing metadata key primary_model", errors)
        self.assertIn("missing section '## Stop conditions'", errors)

    def test_duplicate_work_ids_are_reported(self):
        self.write(
            "docs/prompts/open/first.md",
            prompt(work_id="same-id", status="live", issue="3"),
        )
        self.write(
            "docs/prompts/discovery/second.md",
            prompt(work_id="same-id", status="discovery"),
        )
        errors = "\n".join(check_planning_pack.validate(self.root))
        self.assertIn("duplicate work_id 'same-id'", errors)

    def test_dependencies_must_name_known_work_ids_and_have_no_cycles(self):
        self.write(
            "docs/prompts/proposed/first.md",
            prompt(work_id="first", depends_on="second"),
        )
        self.write("docs/planning/issue-drafts/first.md", issue_draft())
        errors = "\n".join(check_planning_pack.validate(self.root))
        self.assertIn("unknown depends_on work ID: second", errors)

        self.write(
            "docs/prompts/discovery/second.md",
            prompt(work_id="second", status="discovery", depends_on="first"),
        )
        self.write("docs/planning/issue-drafts/second.md", issue_draft())
        errors = "\n".join(check_planning_pack.validate(self.root))
        self.assertIn("dependency cycle:", errors)

        self.write(
            "docs/prompts/discovery/second.md",
            prompt(work_id="second", status="discovery"),
        )
        self.assertEqual(check_planning_pack.validate(self.root), [])

    def test_work_id_is_lowercase_kebab_case(self):
        self.write(
            "docs/prompts/proposed/sample.md",
            prompt(work_id="Not valid"),
        )
        errors = "\n".join(check_planning_pack.validate(self.root))
        self.assertIn("work_id must be lowercase kebab-case", errors)

    def test_invalid_model_status_issue_and_commit_are_reported(self):
        self.write(
            "docs/prompts/proposed/sample.md",
            prompt(
                status="live",
                issue="not-an-issue",
                primary_model="imaginary-model",
                validation_model="another-model",
                commit="short",
            ),
        )
        errors = "\n".join(check_planning_pack.validate(self.root))
        self.assertIn("does not match directory status", errors)
        self.assertIn("non-live prompt issue must be pending or a positive integer", errors)
        self.assertIn("unsupported primary_model", errors)
        self.assertIn("unsupported validation_model", errors)
        self.assertIn("last_reviewed_commit must be 40", errors)

    def test_incomplete_issue_draft_is_reported(self):
        self.write("docs/prompts/discovery/sample.md", prompt(status="discovery"))
        self.write(
            "docs/planning/issue-drafts/sample.md",
            issue_draft(omit="Acceptance criteria"),
        )
        errors = "\n".join(check_planning_pack.validate(self.root))
        self.assertIn("missing section '## Acceptance criteria'", errors)

    def test_issue_draft_needs_a_matching_prompt(self):
        self.write("docs/planning/issue-drafts/unmatched.md", issue_draft())
        errors = "\n".join(check_planning_pack.validate(self.root))
        self.assertIn("no matching proposed or discovery prompt", errors)

    def test_proposed_prompt_needs_a_matching_issue_draft(self):
        self.write("docs/prompts/proposed/orphan.md", prompt())
        errors = "\n".join(check_planning_pack.validate(self.root))
        self.assertIn("proposed or discovery prompt has no matching draft: orphan", errors)

    def test_canonical_repository_paths_must_exist(self):
        self.write(
            "docs/prompts/proposed/sample.md",
            prompt(canonical_sources="issue-draft, docs/ROADMAP.md, https://example.test/x"),
        )
        self.write("docs/planning/issue-drafts/sample.md", issue_draft())
        errors = "\n".join(check_planning_pack.validate(self.root))
        self.assertIn("canonical source does not exist: docs/ROADMAP.md", errors)
        self.write("docs/ROADMAP.md", "# Roadmap\n")
        self.assertEqual(check_planning_pack.validate(self.root), [])

    def test_canonical_repository_paths_cannot_escape_root(self):
        outside = self.root.parent / "outside-planning-source"
        outside.write_text("outside", encoding="utf-8")
        self.addCleanup(outside.unlink)
        self.write(
            "docs/prompts/proposed/sample.md",
            prompt(canonical_sources="docs/../../outside-planning-source"),
        )
        errors = "\n".join(check_planning_pack.validate(self.root))
        self.assertIn("canonical source leaves repository", errors)

    def test_relative_markdown_links_are_checked_and_external_links_are_skipped(self):
        text = prompt() + (
            "\n[Present](../../source.md) [Missing](../../missing.md) "
            "[Section](#scope) [Web](https://example.test) [Mail](mailto:test@example.test)\n"
        )
        self.write("docs/prompts/proposed/sample.md", text)
        self.write("docs/planning/issue-drafts/sample.md", issue_draft())
        self.write("docs/source.md", "# Source\n")
        errors = "\n".join(check_planning_pack.validate(self.root))
        self.assertIn("relative Markdown link does not exist: ../../missing.md", errors)
        self.assertNotIn("example.test", errors)
        self.write("docs/missing.md", "# Missing\n")
        self.assertEqual(check_planning_pack.validate(self.root), [])

    def test_work_program_relative_links_are_checked(self):
        self.write("docs/WORK_PROGRAM.md", "[Missing](missing.md)\n")
        errors = "\n".join(check_planning_pack.validate(self.root))
        self.assertIn("docs/WORK_PROGRAM.md: relative Markdown link does not exist", errors)
        self.write("docs/missing.md", "# Present\n")
        self.assertEqual(check_planning_pack.validate(self.root), [])

    @unittest.skipUnless((REPO / "docs" / "prompts").is_dir(), "planning pack not present")
    def test_committed_repository_pack_is_valid(self):
        self.assertEqual(check_planning_pack.validate(REPO, require_pack=True), [])


if __name__ == "__main__":
    unittest.main()
