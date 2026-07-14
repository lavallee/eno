"""Smoke tests for the new step-2 CLI subcommands. Exercises LocalBackend path."""

import json
from pathlib import Path

from eno.cli import main


def _seed(tmp_path: Path) -> None:
    (tmp_path / "Alpha.md").write_text("# Alpha\n\nlink to [[Beta]] and [[Imaginary]]\n")
    (tmp_path / "Beta.md").write_text("# Beta\n\nback to [[Alpha]]\n")
    (tmp_path / "Orphan.md").write_text("# Orphan\n\nnothing inbound")
    main(["--vault", str(tmp_path), "index"])


def test_orphans_text(tmp_path, capsys):
    _seed(tmp_path)
    capsys.readouterr()
    rc = main(["--vault", str(tmp_path), "orphans"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Orphan.md" in out


def test_orphans_json(tmp_path, capsys):
    _seed(tmp_path)
    capsys.readouterr()
    rc = main(["--vault", str(tmp_path), "--json", "orphans"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    paths = [r["path"] for r in payload]
    assert "Orphan.md" in paths


def test_search(tmp_path, capsys):
    _seed(tmp_path)
    capsys.readouterr()
    rc = main(["--vault", str(tmp_path), "search", "alpha"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Alpha.md" in out


def test_note_with_excerpt(tmp_path, capsys):
    _seed(tmp_path)
    capsys.readouterr()
    rc = main(["--vault", str(tmp_path), "note", "Alpha.md"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Alpha" in out
    assert "excerpt" in out  # the section heading


def test_note_missing_returns_1(tmp_path, capsys):
    _seed(tmp_path)
    capsys.readouterr()
    rc = main(["--vault", str(tmp_path), "note", "Nope.md"])
    assert rc == 1


def test_neighbors(tmp_path, capsys):
    _seed(tmp_path)
    capsys.readouterr()
    rc = main(["--vault", str(tmp_path), "neighbors", "Alpha.md"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "backlinks" in out
    assert "outbound" in out
    assert "Beta.md" in out


def test_broken_links(tmp_path, capsys):
    _seed(tmp_path)
    capsys.readouterr()
    rc = main(["--vault", str(tmp_path), "broken-links"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Imaginary" in out


def test_hygiene(tmp_path, capsys):
    _seed(tmp_path)
    capsys.readouterr()
    rc = main(["--vault", str(tmp_path), "hygiene"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "hygiene:" in out
    assert "missing origin" in out


def test_stubs(tmp_path, capsys):
    _seed(tmp_path)
    capsys.readouterr()
    rc = main(["--vault", str(tmp_path), "stubs"])
    assert rc == 0
    # Orphan and Beta and Alpha are all short — exact contents depend on outbound rule.
    # Just verify it ran cleanly.
    out = capsys.readouterr().out
    assert "Orphan.md" in out  # no outbound, short → stub


def test_hygiene_propose_writes_report(tmp_path, capsys):
    _seed(tmp_path)
    capsys.readouterr()
    out_path = tmp_path / "proposal.md"
    rc = main(
        [
            "--vault",
            str(tmp_path),
            "hygiene",
            "--propose",
            "--out",
            str(out_path),
        ]
    )
    assert rc == 0
    assert out_path.exists()
    text = out_path.read_text()
    assert "Hygiene Proposals" in text
    assert "eno-propose" in text


def test_hygiene_propose_then_apply_roundtrip(tmp_path, capsys):
    _seed(tmp_path)
    capsys.readouterr()
    out_path = tmp_path / "proposal.md"
    main(
        [
            "--vault",
            str(tmp_path),
            "hygiene",
            "--propose",
            "--out",
            str(out_path),
        ]
    )
    capsys.readouterr()

    rc = main(
        ["--vault", str(tmp_path), "hygiene", "--apply", str(out_path)]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "applied:" in out
    # The Orphan note should now have origin set
    new = (tmp_path / "Orphan.md").read_text()
    assert "origin:" in new


def test_create_note_via_cli(tmp_path, capsys):
    capsys.readouterr()
    rc = main(
        [
            "--vault",
            str(tmp_path),
            "create-note",
            "Weaver Skill - Coffee Brewing",
            "--body",
            "coffee notes",
            "--author",
            "Weaver",
        ]
    )
    assert rc == 0
    note = tmp_path / "Weaver Skill - Coffee Brewing.md"
    assert note.exists()
    assert "[[Weaver]]" in note.read_text()


def test_append_to_note_via_cli(tmp_path, capsys):
    (tmp_path / "X.md").write_text("# X\n\nfirst\n")
    capsys.readouterr()
    rc = main(
        [
            "--vault",
            str(tmp_path),
            "append-to-note",
            "X.md",
            "--content",
            "appended via cli",
        ]
    )
    assert rc == 0
    assert "appended via cli" in (tmp_path / "X.md").read_text()


def test_append_to_note_refuses_empty(tmp_path, capsys):
    (tmp_path / "X.md").write_text("# X\n")
    rc = main(["--vault", str(tmp_path), "append-to-note", "X.md", "--content", ""])
    assert rc == 2


def test_garden_writes_report(tmp_path, capsys):
    _seed(tmp_path)
    capsys.readouterr()
    out_path = tmp_path / "garden.md"
    rc = main(["--vault", str(tmp_path), "garden", "--out", str(out_path)])
    assert rc == 0
    assert out_path.exists()
    text = out_path.read_text()
    assert "Garden Report" in text


def test_garden_print_only(tmp_path, capsys):
    _seed(tmp_path)
    capsys.readouterr()
    rc = main(["--vault", str(tmp_path), "garden", "--print"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "resurfacing:" in out
    assert "concept candidates:" in out


def test_garden_refuses_existing_without_force(tmp_path, capsys):
    _seed(tmp_path)
    out_path = tmp_path / "garden.md"
    out_path.write_text("existing")
    rc = main(["--vault", str(tmp_path), "garden", "--out", str(out_path)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "already exists" in err


def test_hygiene_propose_refuses_existing_without_force(tmp_path, capsys):
    _seed(tmp_path)
    out_path = tmp_path / "proposal.md"
    out_path.write_text("existing")
    rc = main(
        [
            "--vault",
            str(tmp_path),
            "hygiene",
            "--propose",
            "--out",
            str(out_path),
        ]
    )
    assert rc == 2
    err = capsys.readouterr().err
    assert "already exists" in err
