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


# ---- OKF trust surface -----------------------------------------------------


def _seed_okf(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "index.md").write_text('---\nokf_version: "0.2"\n---\n# Bundle\n')
    (bundle / "metric.md").write_text(
        "---\n"
        "type: Metric\n"
        "title: Parcel cost\n"
        "status: stable\n"
        "stale_after: 2020-01-01\n"
        "generated: { by: costing_agent/v3, at: 2026-07-01T10:00:00Z }\n"
        "verified: { by: human:rivera, at: 2026-06-10T09:00:00Z }\n"
        "sources:\n"
        "  - { id: policy, resource: /policy.md, title: Policy }\n"
        "---\n"
        "# Parcel cost\n\nDefined against [the policy](/policy.md).\n"
    )
    (bundle / "policy.md").write_text("---\ntype: Reference\n---\n# Policy\n")
    main(["--vault", str(tmp_path), "index"])


def test_note_prints_trust_line(tmp_path, capsys):
    _seed_okf(tmp_path)
    capsys.readouterr()
    rc = main(["--vault", str(tmp_path), "note", "bundle/metric.md"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "trust: status: stable · generated 2026-07-01 by costing_agent/v3" in out
    assert "verified ×1 (1 human)" in out
    assert "stale 2020-01-01" in out


def test_note_omits_trust_line_when_absent(tmp_path, capsys):
    _seed(tmp_path)
    capsys.readouterr()
    rc = main(["--vault", str(tmp_path), "note", "Alpha.md"])
    assert rc == 0
    assert "trust:" not in capsys.readouterr().out


def test_trust_command_lists_candidates(tmp_path, capsys):
    _seed_okf(tmp_path)
    capsys.readouterr()
    rc = main(["--vault", str(tmp_path), "trust"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "advisory, never rejections" in out
    assert "bundle/metric.md  [stale_after]" in out


def test_trust_command_json(tmp_path, capsys):
    _seed_okf(tmp_path)
    capsys.readouterr()
    rc = main(["--vault", str(tmp_path), "--json", "trust"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["counts"]["stale_after"] == 1
    assert {c["check"] for c in payload["candidates"]} >= {"stale_after"}


def test_trust_command_on_plain_vault(tmp_path, capsys):
    _seed(tmp_path)
    capsys.readouterr()
    rc = main(["--vault", str(tmp_path), "--json", "trust"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["candidates"] == []


def test_neighbors_prints_trust_line(tmp_path, capsys):
    _seed_okf(tmp_path)
    capsys.readouterr()
    rc = main(["--vault", str(tmp_path), "neighbors", "bundle/metric.md"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "trust: status: stable" in out
    assert "bundle/policy.md" in out
