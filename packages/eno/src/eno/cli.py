import argparse
import json
import sys
from dataclasses import asdict, is_dataclass
from pathlib import Path

from .backend import make_backend
from .config import VaultNotConfigured, vault_dir
from .indexer import index_vault
from .views import (
    BrokenLink,
    FrontierNote,
    Hit,
    HotCache,
    HygieneReport,
    Neighborhood,
    NoteRef,
    NoteView,
    TilingReport,
    WriteResult,
)


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.cmd == "index":
            return _cmd_index(args)
        if args.cmd == "service":
            return _cmd_service(args)

        backend = make_backend(vault=vault_dir(args.vault), service_url=args.service)

        dispatch = {
            "search": _cmd_search,
            "note": _cmd_note,
            "neighbors": _cmd_neighbors,
            "orphans": _cmd_orphans,
            "stubs": _cmd_stubs,
            "stale": _cmd_stale,
            "broken-links": _cmd_broken_links,
            "frontier": _cmd_frontier,
            "hot": _cmd_hot,
            "tiling": _cmd_tiling,
            "fold": _cmd_fold,
            "hygiene": _cmd_hygiene,
            "garden": _cmd_garden,
            "create-note": _cmd_create_note,
            "append-to-note": _cmd_append_to_note,
        }
        fn = dispatch.get(args.cmd)
        if fn is None:
            parser.error(f"unknown command: {args.cmd}")
            return 2
        return fn(backend, args)
    except VaultNotConfigured as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="eno", description="vault intelligence")
    p.add_argument("--vault", help="vault path (default: $ENO_VAULT_DIR; required if unset)")
    p.add_argument("--service", help="service URL (default: $ENO_SERVICE_URL)")
    p.add_argument("--json", action="store_true", help="emit JSON instead of human text")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_index = sub.add_parser("index", help="index the vault (writes .eno/index.db)")
    p_index.add_argument("--full", action="store_true", help="reparse all notes")

    p_search = sub.add_parser("search", help="search notes by title or tag")
    p_search.add_argument("query")
    p_search.add_argument("--kind", choices=["title", "tag"], default="title")
    p_search.add_argument("--limit", type=int, default=20)

    p_note = sub.add_parser("note", help="show frontmatter + headings + excerpt for one note")
    p_note.add_argument("path")
    p_note.add_argument("--no-excerpt", action="store_true")

    p_neighbors = sub.add_parser("neighbors", help="backlinks + outbound for a note")
    p_neighbors.add_argument("path")

    p_orphans = sub.add_parser("orphans", help="notes with no inbound links")
    p_orphans.add_argument("--folder", help="filter by folder prefix")
    p_orphans.add_argument("--min-words", type=int, default=0)
    p_orphans.add_argument("--limit", type=int, default=20)

    p_stubs = sub.add_parser("stubs", help="short notes with no outbound links")
    p_stubs.add_argument("--max-words", type=int, default=80)
    p_stubs.add_argument("--limit", type=int, default=20)

    p_stale = sub.add_parser("stale", help="notes whose mtime is past a threshold")
    p_stale.add_argument("--older-than-days", type=int, default=180)
    p_stale.add_argument("--stage", action="append", help="filter to specific stage(s)")
    p_stale.add_argument("--limit", type=int, default=20)

    p_broken = sub.add_parser("broken-links", help="wikilinks whose target doesn't resolve")
    p_broken.add_argument("--limit", type=int, default=50)

    p_frontier = sub.add_parser(
        "frontier",
        help="pages where you're actively reaching outward (high out-degree, "
        "low in-degree, recently touched)",
    )
    p_frontier.add_argument("--folder", help="filter by folder prefix")
    p_frontier.add_argument(
        "--halflife-days", type=float, default=30.0,
        help="recency decay constant. Default 30.",
    )
    p_frontier.add_argument("--limit", type=int, default=20)
    p_frontier.add_argument(
        "--include-nonpositive", action="store_true",
        help="include hub pages (negative score) and zero-score pages",
    )
    p_frontier.add_argument(
        "--exclude-type", action="append", dest="exclude_types",
        help="frontmatter type: to skip (repeatable, e.g. --exclude-type log)",
    )

    p_hot = sub.add_parser(
        "hot",
        help="session-start 'what's hot' bundle: frontier + recent + concepts + agent",
    )
    p_hot.add_argument(
        "--agent",
        help="agent name (e.g. Weaver); reads $ENO_AGENT_NAME if unset",
    )

    p_fold = sub.add_parser(
        "fold",
        help="extractive rollup of a date range of daily notes + recent vault edits "
        "(somm + privacy_class=PRIVATE)",
    )
    p_fold_range = p_fold.add_mutually_exclusive_group()
    p_fold_range.add_argument(
        "--from", dest="from_date",
        help="start date YYYY-MM-DD (with --to). Defaults to 7 days before today.",
    )
    p_fold_range.add_argument(
        "--since-last", action="store_true",
        help="start from the day after the most recent committed fold",
    )
    p_fold_range.add_argument(
        "--list", action="store_true",
        help="enumerate committed folds + supersession chain instead of building",
    )
    p_fold_range.add_argument(
        "--over-folds", nargs="+", metavar="FOLD_ID",
        help="fold-of-folds: synthesize over named child fold IDs (level 2+)",
    )
    p_fold_range.add_argument(
        "--topic-wikilink", metavar="TARGET",
        help="topic fold: notes linking to [[TARGET]] + the target itself",
    )
    p_fold_range.add_argument(
        "--topic-folder", metavar="PREFIX",
        help="topic fold: notes under PREFIX (e.g. '2 Projects/Acme')",
    )
    p_fold_range.add_argument(
        "--topic-tag", metavar="TAG",
        help="topic fold: notes with frontmatter or inline tag TAG",
    )
    p_fold.add_argument(
        "--topic-limit", type=int, default=12,
        help="max sources for a topic fold (default: 12)",
    )
    p_fold.add_argument("--to", dest="to_date", help="end date YYYY-MM-DD (default: today)")
    p_fold.add_argument(
        "--commit", action="store_true",
        help="write to 9 Vault Health/folds/<id>.md (default: dry-run stdout-only)",
    )
    p_fold.add_argument(
        "--force", action="store_true",
        help="overwrite an existing fold with the same id (commit mode only)",
    )
    p_fold.add_argument(
        "--model",
        help=(
            "ollama model for the synthesis (default: qwen3:14b). Smaller "
            "models like gemma4:e4b struggle with strict JSON output."
        ),
    )

    p_tiling = sub.add_parser(
        "tiling",
        help="body-content semantic dedup via embeddings (ollama + nomic-embed-text)",
    )
    p_tiling.add_argument(
        "--threshold", type=float, default=0.80,
        help="review-band floor (default 0.80)",
    )
    p_tiling.add_argument(
        "--error-threshold", type=float, default=0.90,
        help="error-band floor (default 0.90)",
    )
    p_tiling.add_argument("--folder", help="filter by folder prefix")
    p_tiling.add_argument(
        "--min-words", type=int, default=80,
        help="skip notes shorter than this (default 80)",
    )
    p_tiling.add_argument(
        "--model", default="nomic-embed-text",
        help="ollama embed model (cache is per-model)",
    )

    p_hygiene = sub.add_parser("hygiene", help="frontmatter contract audit, proposals, applies")
    g_hyg = p_hygiene.add_mutually_exclusive_group()
    g_hyg.add_argument(
        "--propose",
        action="store_true",
        help="generate a reviewable proposal report under 9 Vault Health/",
    )
    g_hyg.add_argument(
        "--apply",
        metavar="REPORT_PATH",
        help="apply approved proposals from a previously-generated report",
    )
    p_hygiene.add_argument(
        "--include-unknown",
        action="store_true",
        help="for --propose: include low-confidence 'unknown' guesses",
    )
    p_hygiene.add_argument(
        "--out",
        help="for --propose: explicit output path (default: 9 Vault Health/<date>-hygiene-proposals.md)",
    )
    p_hygiene.add_argument(
        "--force",
        action="store_true",
        help="for --propose: overwrite existing report file",
    )
    p_hygiene.add_argument(
        "--dry-run",
        action="store_true",
        help="for --apply: report what would change without writing",
    )

    p_create = sub.add_parser(
        "create-note",
        help="create a new note in the vault (frontmatter auto-populated)",
    )
    p_create.add_argument("path", help="vault-relative path (.md auto-appended)")
    p_create.add_argument(
        "--body",
        help="note body. Use '-' to read from stdin.",
        default=None,
    )
    p_create.add_argument("--title", help="explicit frontmatter title (default: filename stem)")
    p_create.add_argument(
        "--author",
        help="agent name for author wikilink; falls back to $ENO_AGENT_NAME",
    )
    p_create.add_argument(
        "--overwrite", action="store_true", help="replace if note already exists"
    )

    p_append = sub.add_parser(
        "append-to-note",
        help="append content to an existing note, optionally under a heading",
    )
    p_append.add_argument("path", help="vault-relative path of the existing note")
    p_append.add_argument(
        "--content",
        help="content to append. Use '-' to read from stdin.",
        default=None,
    )
    p_append.add_argument(
        "--under-heading",
        help="insert under this heading (e.g. '## State'); default: append at end",
    )

    p_garden = sub.add_parser(
        "garden",
        help="run the structural gardener; writes a dated report to 9 Vault Health/",
    )
    p_garden.add_argument("--folder", help="restrict resurfacing to a folder prefix")
    p_garden.add_argument(
        "--out",
        help="explicit report path (default: 9 Vault Health/<date>-garden.md)",
    )
    p_garden.add_argument(
        "--force",
        action="store_true",
        help="overwrite existing garden report at the same path",
    )
    p_garden.add_argument(
        "--print",
        dest="print_only",
        action="store_true",
        help="don't write a report file; print summary to stdout",
    )
    p_garden.add_argument(
        "--resurfacing-min-words",
        type=int,
        default=1000,
        help="threshold for surfacing orphans as resurfacing candidates",
    )
    p_garden.add_argument(
        "--drift-threshold",
        type=float,
        default=0.85,
        help="similarity threshold for drift classification (0-1)",
    )
    p_garden.add_argument(
        "--duplicate-threshold",
        type=float,
        default=0.80,
        help="similarity threshold for duplicate-pair detection (0-1)",
    )

    p_service = sub.add_parser("service", help="manage eno-service daemon")
    p_service.add_argument("action", choices=["start"])
    p_service.add_argument("--host", default="127.0.0.1")
    p_service.add_argument("--port", type=int, default=7891)

    return p


# ---- index + service -------------------------------------------------------


def _cmd_index(args) -> int:
    vault = vault_dir(args.vault)
    if not vault.exists():
        print(f"vault not found: {vault}", file=sys.stderr)
        return 2
    stats = index_vault(vault, full=args.full)
    if args.json:
        print(json.dumps(asdict(stats), indent=2))
    else:
        print(
            f"indexed {stats.parsed} of {stats.seen} notes "
            f"({stats.skipped_unchanged} unchanged, {stats.deleted} deleted) "
            f"— {stats.links_resolved} links resolved, {stats.links_broken} broken "
            f"in {stats.elapsed_s:.2f}s"
        )
    return 0


def _cmd_service(args) -> int:
    if args.action == "start":
        try:
            from eno_service.server import serve
        except ImportError:
            print(
                "eno-service not installed. Run `uv sync --all-packages`.",
                file=sys.stderr,
            )
            return 2
        serve(host=args.host, port=args.port)
        return 0
    print(f"action {args.action} not implemented", file=sys.stderr)
    return 2


# ---- query subcommands -----------------------------------------------------


def _cmd_search(backend, args) -> int:
    _emit(args, backend.search(args.query, kind=args.kind, limit=args.limit))
    return 0


def _cmd_note(backend, args) -> int:
    view = backend.note(args.path, with_excerpt=not args.no_excerpt)
    _emit(args, view)
    return 0 if view else 1


def _cmd_neighbors(backend, args) -> int:
    n = backend.neighbors(args.path)
    _emit(args, n)
    return 0 if n else 1


def _cmd_orphans(backend, args) -> int:
    _emit(
        args,
        backend.orphans(
            folder=args.folder, min_words=args.min_words, limit=args.limit
        ),
    )
    return 0


def _cmd_stubs(backend, args) -> int:
    _emit(args, backend.stubs(max_words=args.max_words, limit=args.limit))
    return 0


def _cmd_stale(backend, args) -> int:
    _emit(
        args,
        backend.stale(
            older_than_days=args.older_than_days,
            stages=args.stage,
            limit=args.limit,
        ),
    )
    return 0


def _cmd_broken_links(backend, args) -> int:
    _emit(args, backend.broken_links(limit=args.limit))
    return 0


def _cmd_hot(backend, args) -> int:
    import os
    name = args.agent or os.environ.get("ENO_AGENT_NAME", "")
    _emit(args, backend.hot(agent_name=name))
    return 0


def _cmd_fold(backend, args) -> int:
    """eno fold — needs the LocalBackend's vault path and direct sqlite access.
    Bypasses the Backend protocol since fold isn't an HTTP-friendly operation
    (long-running synthesis, optional commit-to-disk side effect)."""
    from datetime import date, timedelta

    from . import fold as fold_mod
    from .backend import LocalBackend

    if not isinstance(backend, LocalBackend):
        print(
            "eno fold currently runs against the local index only "
            "(--service mode not supported in v1).",
            file=sys.stderr,
        )
        return 2

    if args.list:
        return _cmd_fold_list(backend, args, fold_mod)
    if args.over_folds:
        return _cmd_fold_over_folds(backend, args, fold_mod)
    if args.topic_wikilink or args.topic_folder or args.topic_tag:
        return _cmd_fold_topic(backend, args, fold_mod)

    today = date.today()
    if args.since_last:
        last_end = fold_mod.last_committed_fold_end(backend.vault)
        if last_end:
            start_d = (date.fromisoformat(last_end) + timedelta(days=1))
        else:
            start_d = today - timedelta(days=7)
        range_start = start_d.isoformat()
    elif args.from_date:
        range_start = args.from_date
    else:
        range_start = (today - timedelta(days=7)).isoformat()
    range_end = args.to_date or today.isoformat()

    if range_end < range_start:
        print(f"--to ({range_end}) is before --from ({range_start})", file=sys.stderr)
        return 2

    model = args.model or fold_mod.DEFAULT_FOLD_MODEL
    print(f"Building fold {range_start} → {range_end} (model: {model})…", file=sys.stderr)
    fold = fold_mod.build_fold(
        backend._conn(),
        backend.vault,
        range_start=range_start,
        range_end=range_end,
        model=model,
    )

    if args.json:
        # JSON mode — emit the dataclass shape, useful for downstream tools.
        print(json.dumps(_to_dict(fold), indent=2, default=str, ensure_ascii=False))
    else:
        # Markdown body to stdout. In dry-run this is the deliverable; in
        # commit mode we still echo it for the human-in-the-loop check.
        print(fold_mod.render_markdown(fold))

    if args.commit:
        if not fold.count_check_passed and not args.force:
            print(
                "Refusing to commit: count_check_failed. "
                "Re-run dry-run, audit the failures, then re-issue with --force.",
                file=sys.stderr,
            )
            return 1
        if not fold.count_check_passed:
            print(
                "Committing despite count_check_failed (--force).",
                file=sys.stderr,
            )
        try:
            target = fold_mod.commit(fold, backend.vault, force=args.force)
        except FileExistsError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(
            f"\nCommitted: {target}\nLogged: {backend.vault / fold_mod.FOLD_LOG_REL}",
            file=sys.stderr,
        )

    return 0


def _cmd_fold_list(backend, args, fold_mod) -> int:
    rows = fold_mod.list_committed_folds(backend.vault)
    if args.json:
        print(json.dumps(rows, indent=2, default=str, ensure_ascii=False))
        return 0
    if not rows:
        print("(no committed folds)")
        return 0
    # Build a quick supersession map for visual chain rendering.
    superseded_by_id: dict[str, str] = {
        r["fold_id"]: r["superseded_by"].strip("[]'\"")
        for r in rows
        if r.get("superseded_by")
    }
    print("# Committed folds\n")
    print(f"_{len(rows)} total. Older to newer._\n")
    for r in rows:
        sup = " ⤴ superseded" if r["fold_id"] in superseded_by_id else ""
        children = ""
        if r.get("supersedes"):
            # Frontmatter values arrive as `[[fold-id]]` strings; strip the
            # brackets so the rendered list isn't `[[[fold-id]]]`.
            stripped = [s.strip("[]") for s in r["supersedes"]]
            children = f"  supersedes=[{', '.join(stripped)}]"
        print(
            f"- `L{r['level']}` **{r['fold_id']}** "
            f"({r['range_start']} → {r['range_end']}, n={r['n_sources']}, "
            f"conf={r['confidence']}){sup}{children}"
        )
    return 0


def _cmd_fold_topic(backend, args, fold_mod) -> int:
    if args.topic_wikilink:
        kind, value = "wikilink", args.topic_wikilink
    elif args.topic_folder:
        kind, value = "folder", args.topic_folder
    else:
        kind, value = "tag", args.topic_tag

    model = args.model or fold_mod.DEFAULT_FOLD_MODEL
    print(
        f"Building topic fold ({kind}={value!r}, model: {model})…",
        file=sys.stderr,
    )
    fold = fold_mod.build_topic_fold(
        backend._conn(),
        backend.vault,
        kind=kind,
        value=value,
        limit=args.topic_limit,
        model=model,
    )

    if args.json:
        print(json.dumps(_to_dict(fold), indent=2, default=str, ensure_ascii=False))
    else:
        print(fold_mod.render_markdown(fold))

    if args.commit:
        if not fold.count_check_passed and not args.force:
            print(
                "Refusing to commit: count_check_failed. "
                "Re-run dry-run, audit the failures, then re-issue with --force.",
                file=sys.stderr,
            )
            return 1
        if not fold.count_check_passed:
            print(
                "Committing despite count_check_failed (--force).",
                file=sys.stderr,
            )
        try:
            target = fold_mod.commit(fold, backend.vault, force=args.force)
        except FileExistsError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(f"\nCommitted: {target}", file=sys.stderr)
    return 0


def _cmd_fold_over_folds(backend, args, fold_mod) -> int:
    """Synthesize a higher-level fold from existing committed folds."""
    all_folds = fold_mod.list_committed_folds(backend.vault)
    by_id = {r["fold_id"]: r for r in all_folds}
    children_meta = []
    for fid in args.over_folds:
        if fid not in by_id:
            print(f"unknown fold id: {fid}", file=sys.stderr)
            return 2
        children_meta.append(by_id[fid])

    # Range = union of children's ranges.
    range_start = min(c["range_start"] for c in children_meta)
    range_end = max(c["range_end"] for c in children_meta)

    model = args.model or fold_mod.DEFAULT_FOLD_MODEL
    print(
        f"Building L2 fold from {len(children_meta)} child folds "
        f"({range_start} → {range_end}, model: {model})…",
        file=sys.stderr,
    )
    fold = fold_mod.build_fold_over_folds(
        backend.vault,
        children_meta=children_meta,
        range_start=range_start,
        range_end=range_end,
        model=model,
    )

    if args.json:
        print(json.dumps(_to_dict(fold), indent=2, default=str, ensure_ascii=False))
    else:
        print(fold_mod.render_markdown(fold))

    if args.commit:
        if not fold.count_check_passed and not args.force:
            print(
                "Refusing to commit: count_check_failed. "
                "Re-run dry-run, then re-issue with --force if you've audited.",
                file=sys.stderr,
            )
            return 1
        try:
            target = fold_mod.commit(fold, backend.vault, force=args.force)
        except FileExistsError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(f"\nCommitted: {target}", file=sys.stderr)
    return 0


def _cmd_tiling(backend, args) -> int:
    _emit(
        args,
        backend.tiling(
            threshold=args.threshold,
            error_threshold=args.error_threshold,
            folder=args.folder,
            min_words=args.min_words,
            model=args.model,
        ),
    )
    return 0


def _cmd_frontier(backend, args) -> int:
    _emit(
        args,
        backend.frontier(
            folder=args.folder,
            halflife_days=args.halflife_days,
            limit=args.limit,
            include_nonpositive=args.include_nonpositive,
            exclude_types=args.exclude_types,
        ),
    )
    return 0


def _cmd_hygiene(backend, args) -> int:
    if args.propose:
        return _cmd_hygiene_propose(backend, args)
    if args.apply:
        return _cmd_hygiene_apply(backend, args)
    _emit(args, backend.hygiene())
    return 0


def _cmd_hygiene_propose(backend, args) -> int:
    from .hygiene import default_report_path, render_report

    report = backend.hygiene_propose(include_unknown=args.include_unknown)
    out_path = (
        Path(args.out).expanduser().resolve()
        if args.out
        else default_report_path(vault_dir(args.vault))
    )
    if out_path.exists() and not args.force:
        print(
            f"report already exists: {out_path}\n"
            "  pass --force to overwrite, or --out PATH to redirect",
            file=sys.stderr,
        )
        return 2
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_report(report), encoding="utf-8")
    if args.json:
        print(
            json.dumps(
                {
                    "out": str(out_path),
                    "proposals": len(report.proposals),
                    "total_notes": report.total_notes,
                    "eligible": report.eligible,
                },
                indent=2,
            )
        )
    else:
        print(
            f"wrote {len(report.proposals)} proposals to {out_path}\n"
            f"  ({report.eligible} of {report.total_notes} notes eligible; "
            "review the file in Obsidian, then `eno hygiene --apply <path>`)"
        )
    return 0


def _read_input(arg_value: str | None) -> str:
    """Resolve a --body / --content arg: '-' means stdin, None means empty,
    anything else is the literal text."""
    if arg_value == "-":
        return sys.stdin.read()
    return arg_value or ""


def _cmd_create_note(backend, args) -> int:
    body = _read_input(args.body)
    frontmatter = None
    if args.title:
        frontmatter = {"title": args.title, "origin": "llm"}
        if args.author:
            frontmatter["author"] = f"[[{args.author}]]"
    result = backend.create_note(
        args.path,
        body,
        frontmatter=frontmatter,
        overwrite=args.overwrite,
        author=args.author,
    )
    _emit(args, result)
    return 0 if result.ok else 1


def _cmd_append_to_note(backend, args) -> int:
    content = _read_input(args.content)
    if not content.strip():
        print("nothing to append (use --content TEXT or --content -)", file=sys.stderr)
        return 2
    result = backend.append_to_note(
        args.path, content, under_heading=args.under_heading
    )
    _emit(args, result)
    return 0 if result.ok else 1


def _cmd_garden(backend, args) -> int:
    from .garden import default_garden_report_path, render_garden_report

    report = backend.garden(
        folder=args.folder,
        resurfacing_min_words=args.resurfacing_min_words,
        drift_threshold=args.drift_threshold,
        duplicate_threshold=args.duplicate_threshold,
    )

    if args.print_only:
        if args.json:
            print(json.dumps(asdict(report), indent=2, default=str, ensure_ascii=False))
        else:
            _print_garden_summary(report)
        return 0

    out_path = (
        Path(args.out).expanduser().resolve()
        if args.out
        else default_garden_report_path(vault_dir(args.vault))
    )
    if out_path.exists() and not args.force:
        print(
            f"report already exists: {out_path}\n"
            "  pass --force to overwrite, or --out PATH to redirect",
            file=sys.stderr,
        )
        return 2
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_garden_report(report), encoding="utf-8")
    if args.json:
        print(
            json.dumps(
                {
                    "out": str(out_path),
                    "stats": report.stats,
                    "resurfacing": len(report.resurfacing),
                    "concepts": len(report.concepts),
                    "drift": len(report.drift),
                    "duplicates": len(report.duplicates),
                    "stubs": len(report.stubs),
                    "stale": len(report.stale),
                },
                indent=2,
            )
        )
    else:
        print(f"wrote garden report to {out_path}")
        _print_garden_summary(report)
    return 0


def _print_garden_summary(report) -> None:
    print(f"  generated:          {report.generated_at}")
    print(f"  elapsed:            {report.stats.get('elapsed_s', 0)}s")
    print(f"  resurfacing:        {len(report.resurfacing)}")
    print(f"  concept candidates: {len(report.concepts)}")
    print(f"  drift candidates:   {len(report.drift)}")
    print(f"  duplicates:         {len(report.duplicates)}")
    print(f"  stubs:              {len(report.stubs)}")
    print(f"  stale:              {len(report.stale)}")


def _cmd_hygiene_apply(backend, args) -> int:
    from .hygiene import parse_report

    report_path = Path(args.apply).expanduser().resolve()
    if not report_path.exists():
        print(f"report not found: {report_path}", file=sys.stderr)
        return 2
    text = report_path.read_text(encoding="utf-8")
    proposals = parse_report(text)
    if not proposals:
        print(
            f"no proposals parsed from {report_path}\n"
            "  (check the file has `eno-propose` fenced YAML blocks)",
            file=sys.stderr,
        )
        return 1

    results = backend.hygiene_apply(proposals, dry_run=args.dry_run)
    ok = sum(1 for r in results if r.ok and r.applied)
    skipped = sum(1 for r in results if r.ok and not r.applied)
    failed = sum(1 for r in results if not r.ok)
    suffix = " (dry-run, no files written)" if args.dry_run else ""
    if args.json:
        print(json.dumps([asdict(r) for r in results], indent=2))
    else:
        print(
            f"applied: {ok}, skipped: {skipped}, failed: {failed}{suffix}"
        )
        for r in results:
            if not r.ok:
                print(f"  ✗ {r.path}  {r.error}")
            elif not r.applied:
                print(f"  · {r.path}  ({r.note})")
    return 0 if failed == 0 else 1


# ---- output ----------------------------------------------------------------


def _emit(args, payload) -> None:
    if args.json:
        print(json.dumps(_to_dict(payload), indent=2, default=str, ensure_ascii=False))
        return
    _print_human(payload)


def _to_dict(obj):
    if obj is None:
        return None
    if is_dataclass(obj):
        return asdict(obj)
    if isinstance(obj, list):
        return [_to_dict(o) for o in obj]
    return obj


def _print_human(payload) -> None:
    if payload is None:
        print("(not found)")
        return
    if isinstance(payload, list):
        if not payload:
            print("(none)")
            return
        for item in payload:
            _print_one(item)
        return
    _print_one(payload)


def _print_one(item) -> None:
    if isinstance(item, NoteRef):
        suffix = f"  ({item.word_count} words)" if item.word_count else ""
        print(f"  {item.path}  [{item.title}]{suffix}")
        if item.excerpt:
            print(f"      {item.excerpt}")
    elif isinstance(item, Hit):
        print(f"  {item.path}  [{item.title}]")
    elif isinstance(item, BrokenLink):
        print(f"  {item.src_path}:{item.line_no}  →  [[{item.target_text}]]")
    elif isinstance(item, FrontierNote):
        print(
            f"  {item.score:>6.2f}  out={item.out_degree:<3} in={item.in_degree:<3} "
            f"age={int(item.age_days):>4}d  {item.path}  [{item.title}]"
        )
    elif isinstance(item, NoteView):
        print(f"# {item.title}")
        print(f"({item.path}, {item.word_count} words)")
        if item.frontmatter:
            print("\nfrontmatter:")
            for k, v in item.frontmatter.items():
                print(f"  {k}: {v}")
        if item.headings:
            print("\nheadings:")
            for h in item.headings:
                indent = "  " * (h.level - 1)
                print(f"  {indent}{'#' * h.level} {h.text}")
        if item.excerpt:
            print(f"\nexcerpt:\n{item.excerpt}")
    elif isinstance(item, Neighborhood):
        print(f"# {item.title}  ({item.path})")
        print(f"\nbacklinks ({len(item.backlinks)}):")
        for r in item.backlinks:
            print(f"  {r.path}  [{r.title}]")
        print(f"\noutbound ({len(item.outbound)}):")
        for r in item.outbound:
            print(f"  {r.path}  [{r.title}]")
    elif isinstance(item, WriteResult):
        if item.ok:
            indexed = " (indexed)" if item.indexed else ""
            note = f" — {item.note}" if item.note else ""
            print(f"  ✓ {item.path}{note}{indexed}")
        else:
            print(f"  ✗ {item.path} — {item.error}")
    elif isinstance(item, HotCache):
        agent_label = f" for {item.agent_name}" if item.agent_name else ""
        print(f"# eno hot{agent_label}")
        print(f"_(generated {item.generated_at})_\n")
        print("## Frontier — currently reaching outward\n")
        if item.frontier:
            for f in item.frontier:
                print(
                    f"- **{f.title}** — `{f.path}` "
                    f"(score {f.score:.2f}, out={f.out_degree}, "
                    f"in={f.in_degree}, age {int(f.age_days)}d)"
                )
        else:
            print("_(none)_")
        print("\n## Recent appends — touched in the last 7 days\n")
        if item.recent_appends:
            for r in item.recent_appends:
                print(f"- {r.title} — `{r.path}` ({r.word_count} words)")
        else:
            print("_(none)_")
        print("\n## Top incipient concepts — durable themes (groundwork, not bugs)\n")
        if item.top_concepts:
            for c in item.top_concepts:
                print(f"- [[{c.target_text}]] (mentioned {c.mention_count}×)")
        else:
            print("_(none)_")
        if item.agent_name:
            print(f"\n## Recent {item.agent_name} contributions — last 14 days\n")
            if item.agent_recent:
                for r in item.agent_recent:
                    print(f"- {r.title} — `{r.path}`")
            else:
                print("_(none)_")
    elif isinstance(item, TilingReport):
        if item.error:
            print(f"# eno tiling — ERROR\n\n{item.error}")
            print(
                "\nIs ollama running and the model pulled?\n"
                "  ollama serve\n"
                f"  ollama pull {item.model or 'nomic-embed-text'}"
            )
            return
        print(f"# eno tiling ({item.model})\n")
        print(
            f"_scanned {item.pages_scanned}; embedded {item.pages_embedded}; "
            f"cache hits {item.cache_hits}; "
            f"thresholds error>={item.error_threshold} review>={item.review_threshold}_\n"
        )
        if item.skipped:
            skipped_str = ", ".join(f"{k}={v}" for k, v in sorted(item.skipped.items()))
            print(f"_skipped: {skipped_str}_\n")
        print(f"## Errors (>= {item.error_threshold})\n")
        if item.error_pairs:
            for p in item.error_pairs:
                print(f"- `{p.score:.4f}` {p.path_a} ↔ {p.path_b}")
        else:
            print("_(none)_")
        print(f"\n## Review ({item.review_threshold} ≤ s < {item.error_threshold})\n")
        if item.review_pairs:
            for p in item.review_pairs:
                print(f"- `{p.score:.4f}` {p.path_a} ↔ {p.path_b}")
        else:
            print("_(none)_")
    elif isinstance(item, HygieneReport):
        total = item.counts.get("total", 0)
        print(f"hygiene: {len(item.issues)} of {total} notes have issues")
        for k, v in item.counts.items():
            if k != "total":
                print(f"  missing {k}: {v}")


if __name__ == "__main__":
    raise SystemExit(main())
