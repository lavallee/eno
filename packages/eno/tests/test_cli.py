from pathlib import Path

from eno.cli import main


def test_index_subcommand_smokes(tmp_path: Path, capsys):
    (tmp_path / "X.md").write_text("# X\n")
    rc = main(["--vault", str(tmp_path), "index"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "indexed 1 of 1 notes" in out


def test_missing_vault_returns_2(tmp_path: Path, capsys):
    rc = main(["--vault", str(tmp_path / "nonexistent"), "index"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "vault not found" in err


def test_full_flag_passes_through(tmp_path: Path, capsys):
    (tmp_path / "X.md").write_text("# X\n")
    main(["--vault", str(tmp_path), "index"])
    capsys.readouterr()
    rc = main(["--vault", str(tmp_path), "index", "--full"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "indexed 1 of 1 notes" in out  # --full forces reparse
