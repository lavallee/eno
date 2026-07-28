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


def test_wikilink_anchor_captured():
    raw = "# X\n\nsee [[Other#Section]] and [[Plain]]"
    note = parse_note("x.md", raw)
    assert note.links[0].target_text == "Other"
    assert note.links[0].anchor == "Section"
    assert note.links[1].anchor is None


def test_wikilink_block_ref_stripped_from_anchor():
    raw = "# X\n\nsee [[Other#Section^blk]] and [[Other^blk]]"
    note = parse_note("x.md", raw)
    assert note.links[0].target_text == "Other"
    assert note.links[0].anchor == "Section"
    # Pure block ref: no '#', so no anchor.
    assert note.links[1].target_text == "Other"
    assert note.links[1].anchor is None


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


# ---- markdown links (the OKF cross-linking form) ---------------------------


def test_md_link_target_alias_and_line():
    note = parse_note("x.md", "# X\n\nsee [the orders table](../tables/orders.md) now\n")
    assert len(note.md_links) == 1
    link = note.md_links[0]
    assert link.target_text == "../tables/orders.md"
    assert link.alias == "the orders table"
    assert link.anchor is None
    assert link.line_no == 3


def test_md_link_anchor_split_from_path():
    note = parse_note("x.md", "# X\n\n[orders](orders.md#schema)\n")
    assert note.md_links[0].target_text == "orders.md"
    assert note.md_links[0].anchor == "schema"


def test_md_link_external_schemes_skipped():
    raw = (
        "# X\n\n[web](https://example.invalid/a) [mail](mailto:x@example.invalid) "
        "[proto](//example.invalid/b) [local](local.md)\n"
    )
    note = parse_note("x.md", raw)
    assert [link.target_text for link in note.md_links] == ["local.md"]


def test_md_link_images_skipped():
    note = parse_note("x.md", "# X\n\n![diagram](pic.png) and [real](real.md)\n")
    assert [link.target_text for link in note.md_links] == ["real.md"]


def test_md_links_in_code_fence_and_inline_code_skipped():
    raw = (
        "# X\n\n[real](real.md)\n\n"
        "`[inline](inline.md)`\n\n"
        "```\n[fenced](fenced.md)\n```\n\n"
        "[also real](also.md)\n"
    )
    note = parse_note("x.md", raw)
    assert [link.target_text for link in note.md_links] == ["real.md", "also.md"]


def test_md_link_pure_fragment_is_not_an_edge():
    note = parse_note("x.md", "# X\n\n[jump](#section) and [out](other.md)\n")
    assert [link.target_text for link in note.md_links] == ["other.md"]


def test_md_link_title_attribute_stripped():
    note = parse_note("x.md", '# X\n\n[t](target.md "hover text")\n')
    assert note.md_links[0].target_text == "target.md"


def test_md_link_bundle_absolute_kept_as_written():
    """Resolution is the indexer's job — the parser records the path verbatim."""
    note = parse_note("deep/x.md", "# X\n\n[g](/references/glossary.md)\n")
    assert note.md_links[0].target_text == "/references/glossary.md"


def test_md_and_wikilinks_coexist():
    note = parse_note("x.md", "# X\n\n[[Wiki]] and [md](md.md)\n")
    assert [link.target_text for link in note.links] == ["Wiki"]
    assert [link.target_text for link in note.md_links] == ["md.md"]


def test_footnote_definition_link_is_an_edge():
    """flip's per-claim attribution puts the citation in a footnote definition;
    those lines are ordinary markdown links and must produce edges."""
    raw = "# X\n\nclaim text[^A1]\n\n[^A1]: [Field trial](../references/trial.md)\n"
    note = parse_note("claims/x.md", raw)
    assert [link.target_text for link in note.md_links] == ["../references/trial.md"]
