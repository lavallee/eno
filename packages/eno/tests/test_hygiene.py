"""Tests for the frontmatter hygiene layer: inference rules, propose, render,
parse, apply."""

from pathlib import Path

from eno.config import index_path
from eno.db import open_index
from eno.hygiene import (
    apply_all,
    apply_proposal,
    infer_origin,
    is_daily_note,
    parse_report,
    propose_all,
    render_report,
)
from eno.indexer import index_vault
from eno.views import Proposal

# ---- inference -----------------------------------------------------------


def test_is_daily_note():
    assert is_daily_note("z Daily Notes/2026-04-26.md")
    assert is_daily_note("2026-04-26.md")
    assert not is_daily_note("Some Note.md")
    # Regex is shape-only, doesn't validate real dates — that's fine for our purpose
    assert is_daily_note("2026-13-99.md")


def test_infer_origin_from_agent_author():
    out = infer_origin(
        path="x.md",
        fm={"author": "[[Poke Research Agent]]"},
        word_count=500,
        h2_count=3,
    )
    assert out is not None
    origin, confidence, _ = out
    assert origin == "llm"
    assert confidence == "high"


def test_infer_origin_from_human_author():
    out = infer_origin(
        path="x.md", fm={"author": "[[the user]]"}, word_count=500, h2_count=3
    )
    assert out is not None
    assert out[0] == "human"
    assert out[1] == "high"


def test_infer_origin_skips_daily_note():
    assert (
        infer_origin(
            path="z Daily Notes/2026-04-26.md", fm={}, word_count=100, h2_count=0
        )
        is None
    )


def test_infer_origin_skips_already_set():
    assert (
        infer_origin(
            path="x.md", fm={"origin": "human"}, word_count=100, h2_count=0
        )
        is None
    )


def test_infer_origin_short_no_h2_is_human():
    out = infer_origin(path="x.md", fm={}, word_count=50, h2_count=0)
    assert out[0] == "human"


def test_infer_origin_fully_formed_is_llm():
    out = infer_origin(path="x.md", fm={}, word_count=500, h2_count=3)
    assert out[0] == "llm"


def test_infer_origin_ambiguous_is_unknown():
    out = infer_origin(path="x.md", fm={}, word_count=120, h2_count=1)
    assert out[0] == "unknown"


# ---- propose_all over a vault --------------------------------------------


def _seed(tmp_path: Path) -> None:
    (tmp_path / "Sparse.md").write_text("# Sparse\n\nshort note")
    (tmp_path / "FullyFormed.md").write_text(
        "# A\n\n## One\n\n" + ("word " * 200) + "\n\n## Two\n\nmore prose"
    )
    (tmp_path / "AlreadyClassified.md").write_text(
        "---\norigin: human\nstage: active\n---\n# X\n"
    )
    (tmp_path / "WithAuthor.md").write_text(
        "---\nauthor: '[[GPT-5]]'\n---\n# Authored\n"
    )
    daily = tmp_path / "z Daily Notes"
    daily.mkdir()
    (daily / "2026-04-26.md").write_text("# 2026-04-26\n\ndaily capture")


def test_propose_all_skips_classified_and_dailies(tmp_path: Path):
    _seed(tmp_path)
    index_vault(tmp_path)
    db = open_index(index_path(tmp_path))
    report = propose_all(db)
    paths = {p.path for p in report.proposals}
    assert "AlreadyClassified.md" not in paths
    assert "z Daily Notes/2026-04-26.md" not in paths
    assert "Sparse.md" in paths
    assert "FullyFormed.md" in paths
    assert "WithAuthor.md" in paths


def test_propose_all_origin_assignments(tmp_path: Path):
    _seed(tmp_path)
    index_vault(tmp_path)
    db = open_index(index_path(tmp_path))
    by_path = {p.path: p for p in propose_all(db).proposals}
    assert by_path["Sparse.md"].add == {"origin": "human"}
    assert by_path["FullyFormed.md"].add == {"origin": "llm"}
    assert by_path["WithAuthor.md"].add == {"origin": "llm"}


def test_propose_all_excludes_unknown_by_default(tmp_path: Path):
    # A note that lands in the 'unknown' bucket: 120 words, 1 H2
    body = "word " * 120
    (tmp_path / "Mid.md").write_text(f"# Mid\n\n## H2 only\n\n{body}")
    index_vault(tmp_path)
    db = open_index(index_path(tmp_path))
    report = propose_all(db)
    assert "Mid.md" not in {p.path for p in report.proposals}

    report_with = propose_all(db, include_unknown=True)
    assert "Mid.md" in {p.path for p in report_with.proposals}


# ---- render / parse roundtrip ---------------------------------------------


def test_render_then_parse_roundtrip():
    proposals = [
        Proposal(path="A.md", add={"origin": "llm"}, confidence="medium", reason="r1"),
        Proposal(path="B.md", add={"origin": "human"}, confidence="high", reason="r2"),
    ]
    from eno.views import ProposalReport
    rep = ProposalReport(proposals=proposals, total_notes=10, eligible=2)
    text = render_report(rep, generated_at="2026-04-30 12:00 UTC")
    parsed = parse_report(text)
    assert {p.path for p in parsed} == {"A.md", "B.md"}
    by_path = {p.path: p for p in parsed}
    assert by_path["A.md"].add == {"origin": "llm"}
    assert by_path["B.md"].add == {"origin": "human"}


def test_parse_report_tolerates_user_edits():
    text = """
# Hygiene Proposals

## Some heading

```eno-propose
path: A.md
confidence: medium
reason: original reason
add:
  origin: human
```

`eno-propose` block above was hand-edited from llm to human. Parser must accept.

```eno-propose
path: B.md
add:
  origin: llm
```

```eno-propose
malformed: {[
```
"""
    parsed = parse_report(text)
    assert len(parsed) == 2
    assert {p.path for p in parsed} == {"A.md", "B.md"}


def test_parse_report_skips_blocks_without_required_fields():
    text = """
```eno-propose
path: A.md
```

```eno-propose
add:
  origin: human
```

```eno-propose
path: C.md
add:
  origin: llm
```
"""
    parsed = parse_report(text)
    assert [p.path for p in parsed] == ["C.md"]


# ---- apply ---------------------------------------------------------------


def test_apply_adds_frontmatter_to_note_without_any(tmp_path: Path):
    note = tmp_path / "X.md"
    note.write_text("# X\n\nbody here")
    res = apply_proposal(
        tmp_path, Proposal(path="X.md", add={"origin": "human"}, confidence="high")
    )
    assert res.ok
    assert res.applied == {"origin": "human"}
    new = note.read_text()
    assert new.startswith("---\n")
    assert "origin: human" in new
    assert "body here" in new


def test_apply_merges_into_existing_frontmatter(tmp_path: Path):
    note = tmp_path / "X.md"
    note.write_text("---\ntype: project\n---\n# X\n\nbody")
    res = apply_proposal(
        tmp_path, Proposal(path="X.md", add={"origin": "human"})
    )
    assert res.ok
    new = note.read_text()
    assert "type: project" in new
    assert "origin: human" in new


def test_apply_does_not_overwrite_existing_field(tmp_path: Path):
    note = tmp_path / "X.md"
    note.write_text("---\norigin: human\n---\n# X\n")
    res = apply_proposal(
        tmp_path, Proposal(path="X.md", add={"origin": "llm"})
    )
    assert res.ok
    assert res.applied == {}
    assert "no changes" in (res.note or "")
    assert "origin: human" in note.read_text()


def test_apply_dry_run_does_not_write(tmp_path: Path):
    note = tmp_path / "X.md"
    note.write_text("# X\n")
    original = note.read_text()
    res = apply_proposal(
        tmp_path,
        Proposal(path="X.md", add={"origin": "human"}),
        dry_run=True,
    )
    assert res.ok
    assert res.applied == {"origin": "human"}
    assert note.read_text() == original


def test_apply_missing_note_returns_error(tmp_path: Path):
    res = apply_proposal(tmp_path, Proposal(path="Nope.md", add={"origin": "human"}))
    assert res.ok is False
    assert "not found" in res.error


def test_apply_all_isolates_failures(tmp_path: Path):
    (tmp_path / "Good.md").write_text("# Good\n")
    proposals = [
        Proposal(path="Good.md", add={"origin": "human"}),
        Proposal(path="Missing.md", add={"origin": "llm"}),
    ]
    results = apply_all(tmp_path, proposals)
    assert results[0].ok and results[0].applied == {"origin": "human"}
    assert not results[1].ok
