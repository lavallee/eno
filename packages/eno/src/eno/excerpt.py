"""Build a token-efficient excerpt of a note from disk.

Excerpts are the contract that makes index-first reads cheap: ~400 chars of
prose, frontmatter and code blocks stripped, paragraph boundaries respected.
"""

import re
from pathlib import Path

from .parser import _split_frontmatter

CODE_FENCE = re.compile(r"^\s*```")


def excerpt(vault: Path, rel_path: str, *, max_chars: int = 400) -> str:
    try:
        raw = (vault / rel_path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""
    _, body = _split_frontmatter(raw)

    out: list[str] = []
    in_fence = False
    for line in body.splitlines():
        if CODE_FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        out.append(re.sub(r"^#{1,6}\s+", "", line))
    text = "\n".join(out).strip()

    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars]
    para_break = truncated.rfind("\n\n")
    if para_break > max_chars * 0.5:
        return truncated[:para_break].rstrip() + "…"
    word_break = truncated.rfind(" ")
    if word_break > max_chars * 0.7:
        return truncated[:word_break].rstrip() + "…"
    return truncated.rstrip() + "…"
