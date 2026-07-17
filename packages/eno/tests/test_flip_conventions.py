"""Tests for the pure flip-conventions module — no filesystem needed."""

from eno.flip_conventions import (
    REF_SHAPE_RE,
    extract_flip_id,
    is_bundle_root,
    parse_workspace_toml,
    split_qualified,
)


def test_is_bundle_root_requires_okf_and_flip_key():
    assert is_bundle_root({"okf_version": "0.4", "flip": "0.4"})
    assert not is_bundle_root({"flip": "0.4"})  # missing okf_version
    assert not is_bundle_root({"okf_version": "0.4"})  # missing flip/flip_beat
    assert not is_bundle_root({})
    # Key presence only — values are opaque to eno.
    assert is_bundle_root({"okf_version": None, "flip": None})


def test_is_bundle_root_accepts_flip_beat():
    assert is_bundle_root({"okf_version": "0.4", "flip_beat": "0.4"})


def test_extract_flip_id_all_prefixes():
    for prefix in ("P", "A", "F", "T", "S", "C", "D", "Q", "H", "TH"):
        assert extract_flip_id({"id": f"{prefix}12"}) == f"{prefix}12"


def test_extract_flip_id_rejects():
    for bad in ("X1", "a1", "TH", "A1b", 1, None):
        assert extract_flip_id({"id": bad}) is None
    assert extract_flip_id({}) is None


def test_parse_workspace_toml_happy_path():
    text = (
        '[workspace]\nversion = "0.1"\n\n'
        '[notebooks]\nhosm = "research/hosm"\nfront = "areas/frontier/"\n'
    )
    assert parse_workspace_toml(text) == {
        "hosm": "research/hosm",
        "front": "areas/frontier",  # trailing slash normalized away
    }


def test_parse_workspace_toml_malformed_returns_empty():
    assert parse_workspace_toml("[[[garbage") == {}
    assert parse_workspace_toml("") == {}
    assert parse_workspace_toml('notebooks = "not-a-table"') == {}


def test_parse_workspace_toml_skips_bad_handles_and_nonstr_paths():
    text = (
        "[notebooks]\n"
        'ok = "research/ok"\n'
        'Bad-Handle = "research/bad"\n'
        '"9start" = "research/nine"\n'
        "numeric = 42\n"
    )
    assert parse_workspace_toml(text) == {"ok": "research/ok"}


def test_split_qualified_colon_and_hash_synonym():
    assert split_qualified("hosm:A3", None) == ("hosm", "A3")
    assert split_qualified("hosm", "A3") == ("hosm", "A3")  # deprecated '#' form
    assert split_qualified("hosm:A3", "Section") == ("hosm", "A3")  # colon wins
    assert split_qualified("Hosm:A3", None) is None  # bad handle
    assert split_qualified("hosm:X3", None) is None  # bad id
    assert split_qualified("hosm", "Section") is None  # anchor not id-shaped
    assert split_qualified("hosm", None) is None  # nothing to split


def test_ref_shape_re():
    for good in ("A3", "TH12", "hosm:A3", "hosm#A3", "a-b2:Q4"):
        assert REF_SHAPE_RE.match(good), good
    for bad in ("X3", "a3", "Hosm:A3", "hosm:X3", "hosm:A3#extra", "hosm", "A3b"):
        assert not REF_SHAPE_RE.match(bad), bad
