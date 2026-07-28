"""OKF v0.2 consumer conventions, restated as pure functions (no I/O, no okf package).

eno reads the Open Knowledge Format's portable trust families the way the OKF
spec (§11) says a consumer must: tolerantly. Everything eno knows about OKF
frontmatter lives here:

- Provenance = `sources`, a list of entries whose `resource` names either a
  followable artifact (URL or bundle path) or a scope descriptor eno cannot
  follow. A dangling entry (id only, no resource) is legal.
- Trust = `generated: {by, at}` (who wrote the content, when) and
  `verified: [{by, at}, ...]` (who confirmed it). A bare `verified` mapping
  is one event, not an error — consumers MUST treat it as a one-element list.
- The human tier keys off the `human:` actor prefix (OKF §5.3/§7); flip's
  actor convention matches, so no flip-specific casing is needed.
- Lifecycle = `status` (values opaque — flip extends the vocabulary) and
  `stale_after` (YYYY-MM-DD; stale when today >= stale_after).

Unknown types, unknown keys, and broken links are all legal; nothing here
rejects a document. Trust labels are advisory signals, never truth verdicts.
"""

import re
from datetime import UTC, date, datetime

# Anything scheme-shaped (https:, mailto:, obsidian:) or protocol-relative
# is external — not a bundle edge, not checkable against the index.
EXTERNAL_SCHEME_RE = re.compile(r"^(?:[a-zA-Z][a-zA-Z0-9+.-]*:|//)")

HUMAN_ACTOR_PREFIX = "human:"


def _text(v) -> str | None:
    """Frontmatter value → stripped string, or None.

    pyyaml resolves unquoted ISO timestamps to date/datetime objects, so an
    author's `at: 2026-07-01T10:00:00Z` and `at: '2026-07-01T10:00:00Z'`
    arrive as different Python types. isoformat() normalizes both to the same
    ISO 8601 string, which keeps the columns sortable and comparable.
    """
    if v is None:
        return None
    if isinstance(v, datetime | date):
        return v.isoformat()
    s = str(v).strip()
    return s or None


def parse_generated(fm: dict) -> tuple[str | None, str | None]:
    """Lift `generated: {by, at}` → (by, at); (None, None) when absent/malformed."""
    gen = fm.get("generated")
    if not isinstance(gen, dict):
        return None, None
    return _text(gen.get("by")), _text(gen.get("at"))


def parse_verified(fm: dict) -> list[dict]:
    """Normalize `verified` into a list of event mappings.

    A bare `{by, at}` mapping becomes a one-element list (OKF §5.2 MUST).
    Non-mapping entries are dropped, never raised on.
    """
    raw = fm.get("verified")
    if isinstance(raw, dict):
        return [raw]
    if isinstance(raw, list):
        return [e for e in raw if isinstance(e, dict)]
    return []


def is_human_actor(by: str | None) -> bool:
    """OKF trust tiers key off the `human:` prefix (§5.3)."""
    return bool(by) and by.startswith(HUMAN_ACTOR_PREFIX)


def verified_stats(events: list[dict]) -> tuple[int | None, int | None, str | None]:
    """(count, human_count, latest_at) over normalized verification events.

    (None, None, None) when there are no events — absence carries meaning
    (unverified), so it must stay distinguishable from zero-of-something.
    latest_at prefers parseable timestamps; unparseable ones fall back to
    string max so a sloppy producer still gets *a* recency answer.
    """
    if not events:
        return None, None, None
    human = sum(1 for e in events if is_human_actor(_text(e.get("by"))))
    ats = [a for a in (_text(e.get("at")) for e in events) if a]
    if not ats:
        return len(events), human, None
    parsed = [(parse_when(a), a) for a in ats]
    dated = [(dt, a) for dt, a in parsed if dt is not None]
    latest = max(dated)[1] if dated else max(ats)
    return len(events), human, latest


def parse_sources(fm: dict) -> list[dict]:
    """Normalize `sources` into a list of entry mappings (tolerant: a bare
    mapping is one entry; non-mapping entries are dropped)."""
    raw = fm.get("sources")
    if isinstance(raw, dict):
        return [raw]
    if isinstance(raw, list):
        return [e for e in raw if isinstance(e, dict)]
    return []


def classify_resource(resource) -> str:
    """What kind of thing a `sources[].resource` names.

    'missing'   — no resource at all (a dangling cite keeps just its id)
    'external'  — URL/scheme; eno can't check it, so it never calls it broken
    'note-path' — bundle-path-shaped AND .md: checkable against the index
    'opaque'    — everything else (scope descriptors, non-md bundle assets);
                  deliberately never counted unresolved
    """
    text = _text(resource)
    if text is None:
        return "missing"
    if EXTERNAL_SCHEME_RE.match(text):
        return "external"
    if text.split("#", 1)[0].endswith(".md"):
        return "note-path"
    return "opaque"


def lift_trust_columns(fm: dict) -> dict:
    """Lift the portable OKF trust/lifecycle families into indexable columns.

    `sources_unresolved` is NOT computed here — it needs the vault's path set,
    which is the indexer's job (see indexer._annotate_okf_sources).
    """
    generated_by, generated_at = parse_generated(fm)
    v_count, v_human, v_last = verified_stats(parse_verified(fm))
    sources_count = len(parse_sources(fm)) if "sources" in fm else None
    return {
        "status": _text(fm.get("status")),
        "stale_after": _text(fm.get("stale_after")),
        "generated_by": generated_by,
        "generated_at": generated_at,
        "verified_count": v_count,
        "verified_human": v_human,
        "verified_last_at": v_last,
        "sources_count": sources_count,
    }


def parse_when(s: str | None) -> datetime | None:
    """Tolerant ISO 8601 parse → aware UTC datetime, or None. Accepts date-only
    strings, 'Z' suffixes, and pyyaml's space-separated datetime rendering."""
    text = _text(s)
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def trust_summary(
    *,
    status: str | None = None,
    generated_by: str | None = None,
    generated_at: str | None = None,
    verified_count: int | None = None,
    verified_human: int | None = None,
    stale_after: str | None = None,
    sources_count: int | None = None,
    sources_unresolved: int | None = None,
) -> str | None:
    """One compact trust/currency line for bounded first reads, e.g.
    "generated 2026-07-01 by agent-x · verified ×2 (1 human) · stale 2026-09-23
    · sources: 3 (1 unresolved)". Absent fields say nothing; all-absent → None.
    """
    segments: list[str] = []
    if status:
        segments.append(f"status: {status}")  # colon: an echoed producer field, never eno's verdict
    if generated_by or generated_at:
        seg = "generated"
        if generated_at:
            seg += f" {generated_at[:10]}"
        if generated_by:
            seg += f" by {generated_by}"
        segments.append(seg)
    if verified_count:
        seg = f"verified ×{verified_count}"
        if verified_human:
            seg += f" ({verified_human} human)"
        segments.append(seg)
    if stale_after:
        segments.append(f"stale {stale_after[:10]}")
    if sources_count is not None:
        seg = f"sources: {sources_count}"
        if sources_unresolved:
            seg += f" ({sources_unresolved} unresolved)"
        segments.append(seg)
    return " · ".join(segments) if segments else None
