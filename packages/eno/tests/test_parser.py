from eno.parser import parse_note


def test_basic_frontmatter_and_links():
    raw = (
        "---\n"
        "title: Foo\n"
        "tags: [a, b]\n"
        "---\n"
        "\n"
        "# Foo\n"
        "\n"
        "## Bar\n"
        "\n"
        "link to [[Other]] and [[Q|aliased]]\n"
    )
    note = parse_note("Foo.md", raw)
    assert note.title == "Foo"
    assert "a" in note.tags and "b" in note.tags
    assert [(h.level, h.text) for h in note.headings] == [(1, "Foo"), (2, "Bar")]
    assert len(note.links) == 2
    assert note.links[0].target_text == "Other"
    assert note.links[0].alias is None
    assert note.links[1].target_text == "Q"
    assert note.links[1].alias == "aliased"


def test_no_frontmatter_uses_h1():
    note = parse_note("foo.md", "# My Title\n\nbody here")
    assert note.title == "My Title"
    assert note.frontmatter == {}


def test_no_frontmatter_no_h1_falls_back_to_filename():
    note = parse_note("Some Note.md", "just body")
    assert note.title == "Some Note"


def test_inline_tags_extracted():
    note = parse_note("x.md", "# X\n\nthis has #foo and #bar/baz tags")
    assert "foo" in note.tags
    assert "bar/baz" in note.tags


def test_aliases_from_frontmatter():
    raw = "---\ntitle: X\naliases: [Why, Z]\n---\n# X\n"
    note = parse_note("x.md", raw)
    assert "Why" in note.aliases and "Z" in note.aliases


def test_headings_in_code_fence_ignored():
    raw = "# Real\n\n```\n# Not a heading\n```\n\n## Also Real\n"
    note = parse_note("x.md", raw)
    assert [h.text for h in note.headings] == ["Real", "Also Real"]


def test_wikilinks_in_code_fence_ignored():
    raw = "# X\n\n[[Real]]\n\n```\n[[Fake]]\n```\n\n[[AlsoReal]]\n"
    note = parse_note("x.md", raw)
    targets = [link.target_text for link in note.links]
    assert "Real" in targets
    assert "AlsoReal" in targets
    assert "Fake" not in targets


def test_wikilink_section_anchor_stripped_for_target():
    raw = "# X\n\nsee [[Other#Section]] and [[Other^block]]"
    note = parse_note("x.md", raw)
    assert [link.target_text for link in note.links] == ["Other", "Other"]


def test_word_count_strips_code_and_heading_markers():
    raw = "# Title\n\nfoo bar\n\n```\nthis should not count\n```\n\nbaz qux"
    note = parse_note("x.md", raw)
    # Heading TEXT counts as content, code fences and `#` markers do not.
    # "Title" + "foo" + "bar" + "baz" + "qux" = 5
    assert note.word_count == 5


def test_content_hash_is_stable():
    raw = "# X\nbody"
    a = parse_note("x.md", raw)
    b = parse_note("x.md", raw)
    assert a.content_hash == b.content_hash


def test_inline_tag_in_word_not_matched():
    note = parse_note("x.md", "# X\n\nemail address foo@bar#baz should not tag")
    assert "baz" not in note.tags


def test_frontmatter_title_wins_over_h1():
    raw = "---\ntitle: From Frontmatter\n---\n# Different H1\n"
    note = parse_note("x.md", raw)
    assert note.title == "From Frontmatter"


def test_malformed_frontmatter_treated_as_body():
    raw = "---\nthis is not yaml: [unclosed\n---\n# Real\n"
    note = parse_note("x.md", raw)
    # YAMLError → fm = {}; body still has the broken yaml lines, but title falls back to H1
    assert note.title == "Real"
