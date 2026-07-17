"""Flip on-disk conventions, restated as pure functions (no I/O, no flip import).

eno never depends on the flip package — everything it knows about flip lives here:

- Bundle root = an `index.md` whose frontmatter has `okf_version` plus either
  `flip` (notebook) or `flip_beat` (beat). Key-presence only; values are opaque.
- Entity page = any page whose frontmatter `id` matches FLIP_ID_RE (uppercase,
  case-sensitive). The flip spec also requires the id in `aliases`, but eno
  lifts from `id:` alone (enforcing the alias is flip doctor's job).
- Workspace table = `<vault>/.flip/workspace.toml`, `[notebooks]` section mapping
  handle -> vault-relative bundle path. Handles match HANDLE_RE.
- Reference forms: bare `[[A3]]` resolves within the containing bundle; qualified
  `[[handle:A3]]` via the workspace table; legacy `[[handle#A3]]` is a deprecated
  read-only synonym for `:`. Unknown handle or id -> unresolved, never a guess.
"""

import re
import tomllib
from pathlib import PurePosixPath

FLIP_ID_RE = re.compile(r"^(?:P|A|F|T|S|C|D|Q|H|TH)\d+$")
HANDLE_RE = re.compile(r"^[a-z][a-z0-9-]*$")
REF_SHAPE_RE = re.compile(r"^(?:[a-z][a-z0-9-]*[:#])?(?:P|A|F|T|S|C|D|Q|H|TH)\d+$")


def is_bundle_root(frontmatter: dict) -> bool:
    """True when the frontmatter marks a flip bundle root (notebook or beat)."""
    return "okf_version" in frontmatter and (
        "flip" in frontmatter or "flip_beat" in frontmatter
    )


def extract_flip_id(frontmatter: dict) -> str | None:
    """Lift a flip entity id from frontmatter `id:`, or None if absent/invalid."""
    fid = frontmatter.get("id")
    if isinstance(fid, str) and FLIP_ID_RE.match(fid):
        return fid
    return None


def parse_workspace_toml(text: str) -> dict[str, str]:
    """Parse workspace.toml text into handle -> normalized posix relpath.

    Returns {} on TOMLDecodeError or a missing/non-dict [notebooks] table.
    Silently skips entries with bad handle syntax or non-string paths.
    """
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return {}
    notebooks = data.get("notebooks")
    if not isinstance(notebooks, dict):
        return {}
    out: dict[str, str] = {}
    for handle, path in notebooks.items():
        if not isinstance(handle, str) or not HANDLE_RE.match(handle):
            continue
        if not isinstance(path, str) or not path.strip():
            continue
        norm = PurePosixPath(path.strip()).as_posix()
        if norm == ".":
            norm = ""
        out[handle] = norm
    return out


def split_qualified(target_text: str, anchor: str | None) -> tuple[str, str] | None:
    """Split a qualified flip reference into (handle, id), or None.

    `"hosm:A3"` -> ("hosm", "A3"); target `"hosm"` with anchor `"A3"` (the
    deprecated `#` synonym) -> ("hosm", "A3"). None when either side fails
    HANDLE_RE / FLIP_ID_RE.
    """
    if ":" in target_text:
        handle, _, ident = target_text.partition(":")
    elif anchor is not None:
        handle, ident = target_text, anchor
    else:
        return None
    if HANDLE_RE.match(handle) and FLIP_ID_RE.match(ident):
        return handle, ident
    return None
