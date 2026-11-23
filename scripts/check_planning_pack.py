"""Validate the maintainer work program's prompts and proposed issue drafts.

The check is deliberately standard-library only so it can run with the other
host-side script tests. It validates the small, one-line metadata format used by
``docs/prompts``; it is not a general YAML or Markdown parser.
"""

from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]

PROMPT_DIRECTORIES = {
    "open": "live",
    "proposed": "proposed",
    "discovery": "discovery",
}
REQUIRED_METADATA = (
    "work_id",
    "status",
    "issue",
    "primary_model",
    "reasoning_effort",
    "validation_model",
    "depends_on",
    "approval_gates",
    "canonical_sources",
    "last_reviewed_commit",
)
REQUIRED_PROMPT_SECTIONS = (
    "Outcome",
    "Baseline and authority",
    "Scope",
    "Non-goals",
    "Interfaces and data flow",
    "Safety and approval gates",
    "Implementation steps",
    "Verification",
    "Documentation and evidence",
    "Stop conditions",
)
REQUIRED_ISSUE_SECTIONS = (
    "User problem and intended outcome",
    "Current state",
    "Scope",
    "Non-goals",
    "Capabilities and data flows",
    "Dependencies and unresolved decisions",
    "Acceptance criteria",
    "Security, privacy, failure handling and data preservation",
    "Evidence expected",
    "Documentation affected",
    "Contributor notes",
    "Links",
)
ALLOWED_MODELS = frozenset({"gpt-6.2-astra", "gpt-6.2-sol", "gpt-6.1-terra"})
ALLOWED_VALIDATION_MODELS = ALLOWED_MODELS | {"none", "human"}
COMMIT = re.compile(r"[0-9a-f]{40}")
NUMBER = re.compile(r"[1-9][0-9]*")
WORK_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
MARKDOWN_LINK = re.compile(r"!?\[[^\]\n]*\]\(([^)\n]+)\)")
LOCAL_SOURCE_PREFIXES = ("docs/", "backend/", "frontend/", "scripts/", ".github/")
LOCAL_SOURCE_FILES = frozenset({"README.md", "SECURITY.md", "CONTRIBUTING.md", "AGENTS.md"})


def _label(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _headings(text: str) -> set[str]:
    return {line[3:].strip() for line in text.splitlines() if line.startswith("## ")}


def _canonical_source_errors(metadata: dict[str, str], label: str, root: Path) -> list[str]:
    errors = []
    resolved_root = root.resolve()
    for source in metadata.get("canonical_sources", "").split(","):
        source = source.strip()
        path_text = source.split("#", 1)[0]
        if not (path_text in LOCAL_SOURCE_FILES or path_text.startswith(LOCAL_SOURCE_PREFIXES)):
            continue
        candidate = (root / unquote(path_text)).resolve()
        try:
            candidate.relative_to(resolved_root)
        except ValueError:
            errors.append(f"{label}: canonical source leaves repository: {source}")
            continue
        if not candidate.exists():
            errors.append(f"{label}: canonical source does not exist: {source}")
    return errors


def _relative_link_errors(path: Path, text: str, root: Path) -> list[str]:
    errors = []
    resolved_root = root.resolve()
    for raw_target in MARKDOWN_LINK.findall(text):
        target = raw_target.strip()
        if target.startswith("<") and target.endswith(">"):
            target = target[1:-1].strip()
        elif " " in target:
            # A Markdown link may have a quoted title after the target.
            target = target.split(None, 1)[0]
        lowered = target.lower()
        if (
            not target
            or target.startswith(("#", "/"))
            or lowered.startswith(("http://", "https://", "mailto:"))
            or any(marker in target for marker in ("{", "}", "<", ">", "..."))
        ):
            continue
        target = unquote(target.split("#", 1)[0].split("?", 1)[0])
        if not target:
            continue
        candidate = (path.parent / target).resolve()
        try:
            candidate.relative_to(resolved_root)
        except ValueError:
            errors.append(
                f"{_label(path, root)}: relative Markdown link leaves repository: {raw_target}"
            )
            continue
        if not candidate.exists():
            errors.append(
                f"{_label(path, root)}: relative Markdown link does not exist: {raw_target}"
            )
    return errors


def _frontmatter(text: str, label: str) -> tuple[dict[str, str], list[str]]:
    errors: list[str] = []
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        return {}, [f"{label}: prompt must start with --- frontmatter"]
    try:
        end = lines.index("---", 1)
    except ValueError:
        return {}, [f"{label}: frontmatter has no closing ---"]

    metadata: dict[str, str] = {}
    for line_number, line in enumerate(lines[1:end], start=2):
        if not line or line[:1].isspace() or ":" not in line:
            errors.append(
                f"{label}:{line_number}: metadata must be one non-indented 'key: value' line"
            )
            continue
        key, value = line.split(":", 1)
        key, value = key.strip(), value.strip()
        if not key or not value:
            errors.append(f"{label}:{line_number}: metadata key and value must be nonempty")
            continue
        if key in metadata:
            errors.append(f"{label}:{line_number}: duplicate metadata key {key}")
            continue
        metadata[key] = value
    return metadata, errors


def _validate_prompt(
    path: Path, root: Path, expected_status: str
) -> tuple[dict[str, str], list[str]]:
    label = _label(path, root)
    errors: list[str] = []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return {}, [f"{label}: cannot read prompt: {type(exc).__name__}"]

    metadata, frontmatter_errors = _frontmatter(text, label)
    errors.extend(frontmatter_errors)
    for key in REQUIRED_METADATA:
        if key not in metadata:
            errors.append(f"{label}: missing metadata key {key}")

    status = metadata.get("status")
    if status is not None and status != expected_status:
        errors.append(
            f"{label}: status {status!r} does not match directory status {expected_status!r}"
        )

    issue = metadata.get("issue")
    if issue is not None:
        if expected_status == "live" and NUMBER.fullmatch(issue) is None:
            errors.append(f"{label}: live prompt issue must be a positive integer")
        if expected_status != "live" and issue != "pending" and NUMBER.fullmatch(issue) is None:
            errors.append(f"{label}: non-live prompt issue must be pending or a positive integer")

    primary_model = metadata.get("primary_model")
    if primary_model is not None and primary_model not in ALLOWED_MODELS:
        errors.append(f"{label}: unsupported primary_model {primary_model!r}")
    validation_model = metadata.get("validation_model")
    if validation_model is not None and validation_model not in ALLOWED_VALIDATION_MODELS:
        errors.append(f"{label}: unsupported validation_model {validation_model!r}")
    effort = metadata.get("reasoning_effort")
    if effort is not None and effort != "ultra":
        errors.append(f"{label}: reasoning_effort must be 'ultra'")
    commit = metadata.get("last_reviewed_commit")
    if commit is not None and COMMIT.fullmatch(commit) is None:
        errors.append(f"{label}: last_reviewed_commit must be 40 lowercase hexadecimal digits")
    work_id = metadata.get("work_id")
    if work_id is not None and WORK_ID.fullmatch(work_id) is None:
        errors.append(f"{label}: work_id must be lowercase kebab-case")
    errors.extend(_canonical_source_errors(metadata, label, root))
    errors.extend(_relative_link_errors(path, text, root))

    headings = _headings(text)
    for section in REQUIRED_PROMPT_SECTIONS:
        if section not in headings:
            errors.append(f"{label}: missing section '## {section}'")
    return metadata, errors


def _dependency_errors(
    dependencies: dict[str, tuple[str, str]], work_ids: set[str]
) -> tuple[list[str], dict[str, tuple[str, ...]]]:
    errors: list[str] = []
    graph: dict[str, tuple[str, ...]] = {}
    for work_id, (label, raw) in sorted(dependencies.items()):
        if raw == "none":
            graph[work_id] = ()
            continue
        values = tuple(value.strip() for value in raw.split(","))
        if any(not value for value in values) or "none" in values:
            errors.append(f"{label}: depends_on must be 'none' or comma-separated work IDs")
            continue
        graph[work_id] = values
        for value in values:
            if value == work_id:
                errors.append(f"{label}: prompt cannot depend on itself")
            elif value not in work_ids:
                errors.append(f"{label}: unknown depends_on work ID: {value}")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(work_id: str, trail: tuple[str, ...]) -> None:
        if work_id in visiting:
            start = trail.index(work_id)
            cycle = trail[start:]
            errors.append(f"dependency cycle: {' -> '.join(cycle)}")
            return
        if work_id in visited:
            return
        visiting.add(work_id)
        for dependency in graph.get(work_id, ()):
            if dependency in graph:
                visit(dependency, trail + (dependency,))
        visiting.remove(work_id)
        visited.add(work_id)

    for work_id in sorted(graph):
        visit(work_id, (work_id,))
    return errors, graph


def validate(root: Path = ROOT, *, require_pack: bool = False) -> list[str]:
    """Return every validation error under ``root`` in deterministic order."""
    root = Path(root)
    errors: list[str] = []
    work_ids: defaultdict[str, list[str]] = defaultdict(list)
    dependencies: dict[str, tuple[str, str]] = {}
    proposed_stems: set[str] = set()
    draft_stems: set[str] = set()

    prompt_root = root / "docs" / "prompts"
    if require_pack:
        required_files = (
            root / "docs" / "WORK_PROGRAM.md",
            prompt_root / "README.md",
            prompt_root / "TEMPLATE.md",
            root / "docs" / "planning" / "issue-drafts" / "README.md",
        )
        for path in required_files:
            if not path.is_file():
                errors.append(f"{_label(path, root)}: required planning-pack file is missing")
    for directory, expected_status in PROMPT_DIRECTORIES.items():
        base = prompt_root / directory
        prompt_paths = sorted(base.glob("*.md")) if base.is_dir() else []
        if require_pack and not prompt_paths:
            errors.append(f"{_label(base, root)}: required prompt directory is missing or empty")
        for path in prompt_paths:
            metadata, prompt_errors = _validate_prompt(path, root, expected_status)
            errors.extend(prompt_errors)
            work_id = metadata.get("work_id")
            if work_id:
                label = _label(path, root)
                work_ids[work_id].append(label)
                if "depends_on" in metadata:
                    dependencies[work_id] = (label, metadata["depends_on"])
            if directory in {"proposed", "discovery"}:
                proposed_stems.add(path.stem)

    for work_id, labels in sorted(work_ids.items()):
        if len(labels) > 1:
            errors.append(f"duplicate work_id {work_id!r}: {', '.join(sorted(labels))}")
    dependency_errors, _ = _dependency_errors(dependencies, set(work_ids))
    errors.extend(dependency_errors)

    drafts = root / "docs" / "planning" / "issue-drafts"
    for path in sorted(drafts.glob("*.md")) if drafts.is_dir() else ():
        if path.name == "README.md":
            continue
        label = _label(path, root)
        draft_stems.add(path.stem)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            errors.append(f"{label}: cannot read issue draft: {type(exc).__name__}")
            continue
        headings = _headings(text)
        for section in REQUIRED_ISSUE_SECTIONS:
            if section not in headings:
                errors.append(f"{label}: missing section '## {section}'")
        if path.stem not in proposed_stems:
            errors.append(f"{label}: no matching proposed or discovery prompt")
        errors.extend(_relative_link_errors(path, text, root))

    for stem in sorted(proposed_stems - draft_stems):
        errors.append(f"docs/prompts: proposed or discovery prompt has no matching draft: {stem}")
    if require_pack and not draft_stems:
        errors.append("docs/planning/issue-drafts: no proposed issue drafts found")

    for path in (
        root / "docs" / "WORK_PROGRAM.md",
        root / "docs" / "ROADMAP.md",
        root / "docs" / "prompts" / "README.md",
        root / "docs" / "prompts" / "TEMPLATE.md",
        root / "docs" / "planning" / "issue-drafts" / "README.md",
    ):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            errors.append(f"{_label(path, root)}: cannot read planning index: {type(exc).__name__}")
            continue
        errors.extend(_relative_link_errors(path, text, root))

    return sorted(errors)


def main() -> int:
    errors = validate(require_pack=True)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("PASS: planning prompt metadata and issue drafts")
    return 0


if __name__ == "__main__":
    sys.exit(main())
