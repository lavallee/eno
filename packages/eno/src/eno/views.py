"""Result types shared by the query layer, the service handlers, and the CLI."""

from dataclasses import dataclass, field


@dataclass
class NoteRef:
    path: str
    title: str
    word_count: int = 0
    excerpt: str | None = None


@dataclass
class Hit:
    path: str
    title: str
    score: float = 0.0
    matched_in: str = ""


@dataclass
class BrokenLink:
    src_path: str
    target_text: str
    line_no: int


@dataclass
class HeadingView:
    level: int
    text: str
    line_no: int


@dataclass
class NoteView:
    path: str
    title: str
    word_count: int
    frontmatter: dict
    headings: list[HeadingView] = field(default_factory=list)
    excerpt: str | None = None


@dataclass
class Neighborhood:
    path: str
    title: str
    backlinks: list[NoteRef] = field(default_factory=list)
    outbound: list[NoteRef] = field(default_factory=list)


@dataclass
class HygieneIssue:
    path: str
    missing: list[str] = field(default_factory=list)


@dataclass
class HygieneReport:
    issues: list[HygieneIssue] = field(default_factory=list)
    counts: dict = field(default_factory=dict)


@dataclass
class Proposal:
    path: str
    add: dict[str, str]            # frontmatter fields to insert
    confidence: str = "medium"     # 'high' | 'medium' | 'low' | 'user-edited'
    reason: str = ""


@dataclass
class ProposalReport:
    proposals: list[Proposal] = field(default_factory=list)
    total_notes: int = 0
    eligible: int = 0              # notes lacking the audited fields


@dataclass
class ApplyResult:
    path: str
    ok: bool
    applied: dict[str, str] = field(default_factory=dict)
    error: str | None = None
    note: str | None = None        # info message (e.g. "no changes — already set")


@dataclass
class DriftCandidate:
    """A broken wikilink whose target fuzzy-matches an existing note —
    a real bug class (em-dash drift, casing, trailing punctuation)."""
    target_text: str
    sources: list[dict] = field(default_factory=list)   # [{"src_path", "line_no"}, ...]
    suggested_path: str = ""
    suggested_title: str = ""
    score: float = 0.0


@dataclass
class ConceptCandidate:
    """A broken wikilink whose target matches no existing note —
    intentional groundwork (incipient), not a bug. Surfaces what
    the user has gestured at but not yet written."""
    target_text: str
    sources: list[dict] = field(default_factory=list)
    mention_count: int = 0


@dataclass
class DuplicatePair:
    path_a: str
    path_b: str
    title_a: str
    title_b: str
    score: float = 0.0


@dataclass
class TilingReport:
    """Body-content duplicate detection via embedding cosine similarity.

    Two bands, mirroring the upstream DragonScale Mechanism 3 convention:
    - error_pairs: similarity >= 0.90 (strong near-duplicates; likely the same idea)
    - review_pairs: 0.80 <= similarity < 0.90 (possible tile overlap; human judgement)

    Read-only signal — never auto-merges. Complements garden.find_duplicates
    (title-based) with a body-content axis.
    """
    error_pairs: list[DuplicatePair] = field(default_factory=list)
    review_pairs: list[DuplicatePair] = field(default_factory=list)
    pages_scanned: int = 0
    pages_embedded: int = 0
    cache_hits: int = 0
    skipped: dict = field(default_factory=dict)
    model: str = ""
    error_threshold: float = 0.90
    review_threshold: float = 0.80
    error: str | None = None  # set when ollama unreachable / model missing


@dataclass
class WriteResult:
    """Outcome of a write operation against a vault note."""
    path: str
    ok: bool
    indexed: bool = False           # True if index was refreshed after the write
    error: str | None = None
    note: str | None = None         # info message ("created", "appended under H2", etc.)


@dataclass
class FrontierNote:
    """A note pointing outward more than it's pointed at, recently touched.

    score = (out_degree - in_degree) * exp(-age_days / halflife_days). High score
    surfaces vault frontiers (where the user is actively reaching). Compare to
    orphans (in_degree=0, no recency) and stale (recency only).
    """
    path: str
    title: str
    word_count: int
    out_degree: int
    in_degree: int
    age_days: float
    recency_weight: float
    score: float


@dataclass
class FoldSource:
    """One input note in a fold's source manifest. Tier captures whether the
    note went in as full body (daily) or excerpt (recent vault edit)."""
    path: str
    title: str
    tier: str            # 'daily' | 'recent_edit'
    date: str            # YYYY-MM-DD; mtime-derived for recent edits
    word_count: int = 0
    excerpt: str = ""


@dataclass
class FoldTheme:
    """An extractive theme: text from sources, plus the dates/notes it cites."""
    text: str
    citations: list[str] = field(default_factory=list)  # ['2026-04-29', '2026-04-30']


@dataclass
class FoldOpenLoop:
    """A pending item the user marked in a source. Preserves original phrasing."""
    text: str
    source_date: str
    source_path: str = ""


@dataclass
class FoldWikilinkHeat:
    """Wikilink mentioned across multiple sources in the fold range."""
    target: str
    count: int
    source_dates: list[str] = field(default_factory=list)
    resolves: bool = False  # True if target_path is non-null in the index


@dataclass
class FoldDaySummary:
    """One-sentence extractive summary per day."""
    date: str
    summary: str
    source_path: str = ""


@dataclass
class Fold:
    """Output of `eno fold`. A bounded, extractive rollup over a date range
    of daily notes + recently-modified vault content. Borrows the wiki-fold
    discipline: deterministic ID, count-checked, additive (never modifies
    children).
    """
    fold_id: str               # fold-{start}-to-{end}-n{count} or fold-L2-...
    range_start: str           # YYYY-MM-DD
    range_end: str             # YYYY-MM-DD
    level: int = 1             # 1 = over raw notes; 2 = over child folds; etc.
    sources: list[FoldSource] = field(default_factory=list)
    themes: list[FoldTheme] = field(default_factory=list)
    open_loops: list[FoldOpenLoop] = field(default_factory=list)
    wikilink_heat: list[FoldWikilinkHeat] = field(default_factory=list)
    day_summaries: list[FoldDaySummary] = field(default_factory=list)
    confidence: str = "medium"  # low | medium | high — overall, count-check pass rate
    count_check_passed: bool = True
    count_check_failures: list[str] = field(default_factory=list)
    generated_at: str = ""
    workload: str = "vault_fold"
    model: str = ""             # actual provider/model that ran the synthesis
    supersedes: list[str] = field(default_factory=list)  # fold_ids contained by this one
    children: list[str] = field(default_factory=list)    # for level>=2: input fold_ids


@dataclass
class HotCache:
    """Recent-context bundle for a fresh agent session.

    Derived on demand from the index (no file persisted) — `eno hot` is the
    eno equivalent of claude-obsidian's `wiki/hot.md`, but computed rather
    than written. Read at SessionStart and after compaction; never stale.
    """
    generated_at: str
    frontier: list[FrontierNote] = field(default_factory=list)
    recent_appends: list[NoteRef] = field(default_factory=list)
    top_concepts: list[ConceptCandidate] = field(default_factory=list)
    agent_recent: list[NoteRef] = field(default_factory=list)
    agent_name: str = ""


@dataclass
class GardenReport:
    generated_at: str = ""
    resurfacing: list[NoteRef] = field(default_factory=list)
    concepts: list[ConceptCandidate] = field(default_factory=list)
    drift: list[DriftCandidate] = field(default_factory=list)
    stubs: list[NoteRef] = field(default_factory=list)
    stale: list[NoteRef] = field(default_factory=list)
    duplicates: list[DuplicatePair] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
