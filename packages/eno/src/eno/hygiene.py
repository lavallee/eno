"""Frontmatter hygiene: infer origin, write a reviewable proposal report,
parse it back, apply approved changes to vault notes.

v0 scope: origin field only. Stage is intentionally not auto-proposed —
it requires human judgment about lifecycle, not text characteristics.

Heuristic rules (in order):
  1. `author` field with agent-y wikilink → llm
  2. `author` field with non-agent value → human
  3. Daily-note filename (YYYY-MM-DD) → skip (always human, but no need to backfill)
  4. Sparse content (< 100 words, no H2) → human (basic capture)
  5. Fully-formed text (≥ 200 words, ≥ 2 H2) → llm
  6. Else → unknown (skipped from proposals unless --include-unknown)
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import yaml

from .parser import FRONTMATTER_RE
from .views import ApplyResult, Proposal, ProposalReport

DAILY_NOTE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
AGENT_HINT_RE = re.compile(
    r"\b(agent|gpt|claude|bot|copilot|cursor|llm|anthropic|openai)\b",
    re.IGNORECASE,
)

SHORT_THRESHOLD = 100
FULLY_FORMED_WORDS = 200
FULLY_FORMED_H2 = 2


def is_daily_note(rel_path: str) -> bool:
    return bool(DAILY_NOTE_RE.match(Path(rel_path).stem))


def _author_origin(author: object) -> str | None:
    """Extract origin from frontmatter `author`. Returns 'llm', 'human', or None."""
    if author is None:
        return None
    text = str(author).strip()
    if not text:
        return None
    m = re.search(r"\[\[([^\]\|]+)", text)
    target = (m.group(1) if m else text).strip()
    if AGENT_HINT_RE.search(target):
        return "llm"
    return "human"


def infer_origin(
    *, path: str, fm: dict, word_count: int, h2_count: int
) -> tuple[str, str, str] | None:
    """Return (origin, confidence, reason) or None if no proposal warranted.

    None when origin is already set or the note is a daily note.
    """
    if fm.get("origin"):
        return None
    if is_daily_note(path):
        return None

    if "author" in fm:
        origin = _author_origin(fm["author"])
        if origin:
            return (origin, "high", f"derived from author={fm['author']!r}")

    if word_count < SHORT_THRESHOLD and h2_count == 0:
        return ("human", "medium", f"sparse note ({word_count} words, no H2)")

    if word_count >= FULLY_FORMED_WORDS and h2_count >= FULLY_FORMED_H2:
        return (
            "llm",
            "medium",
            f"fully-formed text ({word_count} words, {h2_count} H2) without explicit author",
        )

    return ("unknown", "low", f"{word_count} words, {h2_count} H2 — insufficient signal")


def propose_all(
    db: sqlite3.Connection, *, include_unknown: bool = False
) -> ProposalReport:
    h2_counts = dict(
        db.execute(
            "SELECT path, COUNT(*) FROM headings WHERE level = 2 GROUP BY path"
        )
    )

    proposals: list[Proposal] = []
    total = 0
    eligible = 0
    for path, fm_json, word_count in db.execute(
        "SELECT path, frontmatter_json, word_count FROM notes ORDER BY path"
    ):
        total += 1
        try:
            fm = json.loads(fm_json) or {}
        except json.JSONDecodeError:
            fm = {}
        if fm.get("origin") or is_daily_note(path):
            continue
        eligible += 1
        result = infer_origin(
            path=path,
            fm=fm,
            word_count=word_count,
            h2_count=h2_counts.get(path, 0),
        )
        if result is None:
            continue
        origin, confidence, reason = result
        if origin == "unknown" and not include_unknown:
            continue
        proposals.append(
            Proposal(
                path=path,
                add={"origin": origin},
                confidence=confidence,
                reason=reason,
            )
        )
    return ProposalReport(
        proposals=proposals, total_notes=total, eligible=eligible
    )


# ---- report rendering & parsing -------------------------------------------

PROPOSE_FENCE_RE = re.compile(r"```eno-propose\n(.*?)\n```", re.DOTALL)


def render_report(report: ProposalReport, *, generated_at: str | None = None) -> str:
    if generated_at is None:
        generated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    by_conf: dict[str, list[Proposal]] = {"high": [], "medium": [], "low": []}
    for p in report.proposals:
        by_conf.setdefault(p.confidence, []).append(p)

    fm = {
        "kind": "eno-hygiene-proposals",
        "generated_at": generated_at,
        "counts": {
            "total_notes": report.total_notes,
            "eligible": report.eligible,
            "proposals": len(report.proposals),
        },
    }
    fm_text = yaml.safe_dump(
        fm, sort_keys=False, default_flow_style=False, allow_unicode=True, width=10**9
    ).rstrip()

    lines: list[str] = []
    lines.append("---")
    lines.append(fm_text)
    lines.append("---")
    lines.append("")
    lines.append(f"# Hygiene Proposals — {generated_at}")
    lines.append("")
    lines.append(
        f"Generated from {report.total_notes} notes; {report.eligible} lacked `origin`; "
        f"{len(report.proposals)} proposals follow."
    )
    lines.append("")
    lines.append("**Review process**")
    lines.append("")
    lines.append("1. Read each proposal below.")
    lines.append("2. Delete any block (the entire `### [[...]]` section) for proposals you reject.")
    lines.append("3. Edit YAML inside an `eno-propose` block to refine a proposal — your edits win.")
    lines.append("4. Run `eno hygiene --apply \"<this-file>\"` to commit accepted proposals.")
    lines.append("")
    lines.append("---")
    lines.append("")

    for label, props in (
        ("High confidence", by_conf.get("high", [])),
        ("Medium confidence", by_conf.get("medium", [])),
        ("Low confidence", by_conf.get("low", [])),
    ):
        if not props:
            continue
        lines.append(f"## {label} ({len(props)})")
        lines.append("")
        for p in props:
            stem = Path(p.path).stem
            lines.append(f"### [[{p.path[:-3]}|{stem}]]")
            lines.append("")
            block = yaml.safe_dump(
                {
                    "path": p.path,
                    "confidence": p.confidence,
                    "reason": p.reason,
                    "add": p.add,
                },
                default_flow_style=False,
                sort_keys=False,
                allow_unicode=True,
                width=10**9,  # disable wrapping; long paths must stay on one line
            ).rstrip()
            lines.append("```eno-propose")
            lines.append(block)
            lines.append("```")
            lines.append("")
            lines.append("---")
            lines.append("")
    return "\n".join(lines) + "\n"


def parse_report(text: str) -> list[Proposal]:
    """Extract proposals from a report markdown file. Tolerant of user edits."""
    proposals: list[Proposal] = []
    for match in PROPOSE_FENCE_RE.finditer(text):
        try:
            data = yaml.safe_load(match.group(1)) or {}
        except yaml.YAMLError:
            continue
        if not isinstance(data, dict):
            continue
        path = data.get("path")
        add = data.get("add")
        if not path or not isinstance(add, dict) or not add:
            continue
        proposals.append(
            Proposal(
                path=str(path),
                add={str(k): str(v) for k, v in add.items() if v is not None},
                confidence=str(data.get("confidence", "user-edited")),
                reason=str(data.get("reason", "")),
            )
        )
    return proposals


# ---- apply ----------------------------------------------------------------


def apply_proposal(vault: Path, prop: Proposal, *, dry_run: bool = False) -> ApplyResult:
    note_path = vault / prop.path
    if not note_path.exists():
        return ApplyResult(path=prop.path, ok=False, error="note not found")
    try:
        raw = note_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        return ApplyResult(path=prop.path, ok=False, error=f"read failed: {e}")

    m = FRONTMATTER_RE.match(raw)
    if m:
        try:
            fm = yaml.safe_load(m.group(1)) or {}
        except yaml.YAMLError:
            return ApplyResult(
                path=prop.path, ok=False, error="malformed existing frontmatter"
            )
        if not isinstance(fm, dict):
            return ApplyResult(
                path=prop.path, ok=False, error="frontmatter is not a mapping"
            )
        body = raw[m.end():]
    else:
        fm = {}
        body = raw

    actually_added: dict[str, str] = {}
    for k, v in prop.add.items():
        if not fm.get(k):
            fm[k] = v
            actually_added[k] = v

    if not actually_added:
        return ApplyResult(
            path=prop.path,
            ok=True,
            applied={},
            note="no changes — fields already set",
        )

    new_fm = yaml.safe_dump(
        fm,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
        width=10**9,
    ).rstrip()
    new_block = f"---\n{new_fm}\n---\n"
    if not body.startswith("\n"):
        new_block += "\n"
    new_raw = new_block + body

    if dry_run:
        return ApplyResult(path=prop.path, ok=True, applied=actually_added, note="dry-run")

    try:
        note_path.write_text(new_raw, encoding="utf-8")
    except OSError as e:
        return ApplyResult(path=prop.path, ok=False, error=f"write failed: {e}")
    return ApplyResult(path=prop.path, ok=True, applied=actually_added)


def apply_all(
    vault: Path, proposals: list[Proposal], *, dry_run: bool = False
) -> list[ApplyResult]:
    return [apply_proposal(vault, p, dry_run=dry_run) for p in proposals]


# ---- helpers --------------------------------------------------------------


def default_report_path(vault: Path) -> Path:
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    return vault / "9 Vault Health" / f"{today}-hygiene-proposals.md"
