"""Parse a markdown note into structured pieces (frontmatter, headings, wikilinks, tags, aliases).

Stays purely functional. No I/O — caller passes raw text. Same parser will handle .qmd
when we add it (qmd's YAML header and prose share md syntax; the only delta is code blocks
already get stripped for word-count, and qmd-specific fields will live in frontmatter).
"""

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath

import yaml

FRONTMATTER_RE = re.compile(r"\A---\r?\n(.*?\r?\n)---\r?\n?", re.DOTALL)
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
WIKILINK_RE = re.compile(r"\[\[([^\]\|\n]+?)(?:\|([^\]\n]+?))?\]\]")
INLINE_TAG_RE = re.compile(r"(?:^|[^\w&])#([A-Za-z][\w/-]*)")
CODE_FENCE_RE = re.compile(r"^\s*```")


@dataclass
class Heading:
    level: int
    text: str
    line_no: int


@dataclass
class Wikilink:
    target_text: str
    alias: str | None
    line_no: int


@dataclass
class ParsedNote:
    path: str  # vault-relative, posix-style
    title: str
    body: str
    frontmatter: dict
    headings: list[Heading] = field(default_factory=list)
    links: list[Wikilink] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    word_count: int = 0
    content_hash: str = ""


def parse_note(rel_path: str, raw: str) -> ParsedNote:
    frontmatter, body = _split_frontmatter(raw)
    headings, links = _scan_lines(body)
    inline_tags = _parse_inline_tags(_strip_code_blocks(body))
    fm_tags = _frontmatter_list(frontmatter, ("tags",))
    fm_aliases = _frontmatter_list(frontmatter, ("aliases", "alias"))

    title = _derive_title(rel_path, frontmatter, headings)
    word_count = len(_body_for_word_count(body).split())
    content_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()

    tags = sorted({t.lstrip("#") for t in (*inline_tags, *fm_tags) if t})

    return ParsedNote(
        path=rel_path,
        title=title,
        body=body,
        frontmatter=frontmatter,
        headings=headings,
        links=links,
        tags=tags,
        aliases=fm_aliases,
        word_count=word_count,
        content_hash=content_hash,
    )


def _split_frontmatter(raw: str) -> tuple[dict, str]:
    m = FRONTMATTER_RE.match(raw)
    if not m:
        return {}, raw
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        fm = {}
    if not isinstance(fm, dict):
        fm = {}
    return fm, raw[m.end():]


def _scan_lines(body: str) -> tuple[list[Heading], list[Wikilink]]:
    """Single pass over body, tracking code fences. Headings + wikilinks together for efficiency."""
    headings: list[Heading] = []
    links: list[Wikilink] = []
    in_fence = False
    for line_no, line in enumerate(body.splitlines(), start=1):
        if CODE_FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        h = HEADING_RE.match(line)
        if h:
            headings.append(Heading(level=len(h.group(1)), text=h.group(2).strip(), line_no=line_no))
            continue  # heading lines don't get wikilink-scanned (rare and avoids weird edge cases)
        for m in WIKILINK_RE.finditer(line):
            target = m.group(1).strip()
            alias = m.group(2).strip() if m.group(2) else None
            # Strip section anchor (#) and block ref (^) for resolution; keep raw for display.
            target_clean = target.split("#", 1)[0].split("^", 1)[0].strip()
            if not target_clean:
                continue
            links.append(Wikilink(target_text=target_clean, alias=alias, line_no=line_no))
    return headings, links


def _parse_inline_tags(body: str) -> list[str]:
    return [m.group(1) for m in INLINE_TAG_RE.finditer(body)]


def _strip_code_blocks(body: str) -> str:
    """Remove fenced code blocks (```...```). Inline backticks are left alone."""
    out: list[str] = []
    in_fence = False
    for line in body.splitlines():
        if CODE_FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if not in_fence:
            out.append(line)
    return "\n".join(out)


def _body_for_word_count(body: str) -> str:
    """Strip code fences and leading heading markers; heading TEXT still counts as content."""
    out: list[str] = []
    in_fence = False
    for line in body.splitlines():
        if CODE_FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        out.append(re.sub(r"^#{1,6}\s+", "", line))
    return "\n".join(out)


def _frontmatter_list(fm: dict, keys: tuple[str, ...]) -> list[str]:
    for k in keys:
        if k not in fm:
            continue
        raw = fm[k]
        if isinstance(raw, str):
            return [t.strip() for t in raw.replace(",", " ").split() if t.strip()]
        if isinstance(raw, list):
            return [str(t).strip() for t in raw if str(t).strip()]
    return []


def _derive_title(rel_path: str, fm: dict, headings: list[Heading]) -> str:
    fm_title = fm.get("title")
    if isinstance(fm_title, str) and fm_title.strip():
        return fm_title.strip()
    h1s = [h for h in headings if h.level == 1]
    if h1s:
        return h1s[0].text
    return PurePosixPath(rel_path).stem
