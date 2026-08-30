"""Build a bounded project-estate scope from Flip's plain JSONL registry.

Flip owns notebook discovery and stable lineage identity. Eno consumes that
registry without importing Flip, selects one filesystem copy per non-empty
notebook UID, and returns roots that can be indexed relative to one common
estate directory. Full roots (for example an Obsidian vault) may be composed
with the notebook roots.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from . import flip_conventions
from .parser import parse_note


class EstateRegistryError(ValueError):
    """The registry cannot safely define a complete estate scope."""


@dataclass(frozen=True)
class EstateScope:
    roots: tuple[Path, ...]
    registry_path: Path
    notebooks_discovered: int
    notebooks_indexed: int
    duplicate_lineages: int
    shadowed_copies: int
    missing_uids: int
    ignored_hidden_copies: int
    shadows: dict[str, dict[str, object]] = field(default_factory=dict)

    def state(self, vault: Path) -> dict[str, object]:
        return {
            "mode": "flip-estate",
            "vault": str(vault),
            "registry": str(self.registry_path),
            "roots": [p.relative_to(vault).as_posix() or "." for p in self.roots],
            "notebooks_discovered": self.notebooks_discovered,
            "notebooks_indexed": self.notebooks_indexed,
            "duplicate_lineages": self.duplicate_lineages,
            "shadowed_copies": self.shadowed_copies,
            "missing_uids": self.missing_uids,
            "ignored_hidden_copies": self.ignored_hidden_copies,
            "shadows": self.shadows,
        }


def load_estate_scope(
    vault: Path,
    registry_path: Path,
    *,
    include_roots: list[Path] | None = None,
) -> EstateScope:
    """Read a Flip registry and return canonical, non-overlapping index roots.

    Registry notebook paths must resolve beneath ``vault`` and still carry a
    Flip bundle manifest. Rows under dot-directories (worktrees and harness
    copies) are ignored. A repeated non-empty UID is one lineage: the shortest
    vault-relative path wins deterministically and every shadowed copy remains
    visible in state.json. UID-less legacy notebooks cannot be safely merged,
    so each remains indexed and is counted for review.
    """

    vault = vault.expanduser().resolve()
    registry_path = registry_path.expanduser().resolve()
    try:
        lines = registry_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise EstateRegistryError(f"cannot read Flip registry: {registry_path}") from exc

    rows: list[dict] = []
    for line_no, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise EstateRegistryError(f"invalid JSON in Flip registry at line {line_no}") from exc
        if not isinstance(row, dict):
            raise EstateRegistryError(f"non-object row in Flip registry at line {line_no}")
        if row.get("workspace") or "slug" not in row:
            continue
        rows.append(row)

    valid: list[tuple[dict, Path, Path]] = []
    ignored_hidden = 0
    for row in rows:
        raw_path = row.get("path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise EstateRegistryError("Flip registry notebook row has no path")
        root = Path(raw_path).expanduser().resolve()
        try:
            rel = root.relative_to(vault)
        except ValueError as exc:
            raise EstateRegistryError(f"Flip registry path escapes estate root: {root}") from exc
        if any(part.startswith(".") for part in rel.parts):
            ignored_hidden += 1
            continue
        if not _is_flip_bundle(root, vault):
            raise EstateRegistryError(
                f"Flip registry path is missing a valid bundle manifest: {root}"
            )
        valid.append((row, root, rel))

    by_uid: dict[str, list[tuple[dict, Path, Path]]] = {}
    uidless: list[tuple[dict, Path, Path]] = []
    for entry in valid:
        uid = entry[0].get("uid")
        if isinstance(uid, str) and uid.strip():
            by_uid.setdefault(uid.strip(), []).append(entry)
        else:
            uidless.append(entry)

    selected: list[Path] = []
    shadows: dict[str, dict[str, object]] = {}
    shadowed_copies = 0
    duplicate_lineages = 0
    for uid, entries in sorted(by_uid.items()):
        ranked = sorted(entries, key=lambda item: _canonical_rank(item[2]))
        chosen = ranked[0]
        selected.append(chosen[1])
        if len(ranked) > 1:
            duplicate_lineages += 1
            shadowed_copies += len(ranked) - 1
            shadows[uid] = {
                "selected": chosen[2].as_posix(),
                "shadowed": [item[2].as_posix() for item in ranked[1:]],
            }
    selected.extend(item[1] for item in uidless)

    full_roots = [_resolve_include_root(vault, root) for root in (include_roots or [])]
    roots = _collapse_roots(vault, [*full_roots, *selected])
    return EstateScope(
        roots=tuple(roots),
        registry_path=registry_path,
        notebooks_discovered=len(valid),
        notebooks_indexed=len(by_uid) + len(uidless),
        duplicate_lineages=duplicate_lineages,
        shadowed_copies=shadowed_copies,
        missing_uids=len(uidless),
        ignored_hidden_copies=ignored_hidden,
        shadows=shadows,
    )


def _is_flip_bundle(root: Path, vault: Path) -> bool:
    manifest = root / "index.md"
    try:
        raw = manifest.read_text(encoding="utf-8")
        rel = manifest.relative_to(vault).as_posix()
    except (OSError, UnicodeDecodeError, ValueError):
        return False
    return flip_conventions.is_bundle_root(parse_note(rel, raw).frontmatter)


def _canonical_rank(rel: Path) -> tuple[int, int, str]:
    text = rel.as_posix()
    return len(rel.parts), len(text), text


def _resolve_include_root(vault: Path, root: Path) -> Path:
    candidate = root.expanduser()
    if not candidate.is_absolute():
        candidate = vault / candidate
    candidate = candidate.resolve()
    try:
        rel = candidate.relative_to(vault)
    except ValueError as exc:
        raise EstateRegistryError(f"included root escapes estate root: {candidate}") from exc
    if any(part.startswith(".") for part in rel.parts):
        raise EstateRegistryError(f"included root is hidden: {candidate}")
    if not candidate.is_dir():
        raise EstateRegistryError(f"included root is not a directory: {candidate}")
    return candidate


def _collapse_roots(vault: Path, roots: list[Path]) -> list[Path]:
    unique = sorted(
        set(roots),
        key=lambda root: (
            len(root.relative_to(vault).parts),
            root.relative_to(vault).as_posix(),
        ),
    )
    kept: list[Path] = []
    for root in unique:
        if any(root == parent or parent in root.parents for parent in kept):
            continue
        kept.append(root)
    return kept
