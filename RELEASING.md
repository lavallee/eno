# Releasing eno

eno is a `uv` workspace of four packages. The three Python packages (`eno`,
`eno-mcp`, `eno-service`) and the Obsidian plugin (`eno-plugin`) all carry the
**same version number and move in lockstep** — never bump one independently.

## Version locations (bump all together)

- `packages/eno/pyproject.toml` + `packages/eno/src/eno/__init__.py`
- `packages/eno-mcp/pyproject.toml` + `packages/eno-mcp/src/eno_mcp/__init__.py`
- `packages/eno-service/pyproject.toml` + `packages/eno-service/src/eno_service/__init__.py`
- `packages/eno-plugin/manifest.json`
- Any inter-package `==X` pin in a package's `dependencies`.

`scripts/check_release_gate.py` verifies these agree; CI runs it on every push.

## Semver rules

- **Patch** — fixes, docs, no surface change.
- **Minor** — new backward-compatible surface (a CLI subcommand, an MCP tool,
  an endpoint, an extra).
- **Major** — breaking CLI flags, MCP tool signatures, index schema, or a
  change to a load-bearing numeric threshold (tiling similarity bands, drift
  fuzzy-match cutoff, fold count-check rules). Call these out explicitly.

## Checklist

1. `uv run pytest packages/` and `uv run ruff check packages/` pass locally.
2. Bump the version everywhere above, in lockstep.
3. Move `CHANGELOG.md` `[Unreleased]` entries under a new dated `## [X.Y.Z]`
   heading; update the compare/tag links at the bottom.
4. Update the version badge and any new capability on `docs/index.html`.
5. Commit a clean `chore(release): X.Y.Z`.
6. `git tag -a vX.Y.Z -m "vX.Y.Z"` → push `main` and the tag.
7. `gh release create vX.Y.Z` with focused notes and a compare link.
8. Publish to PyPI: `uv build && uv publish` (or a trusted-publish workflow
   triggered by the GitHub release).

## Publishing

This repository is public. Before pushing any release, confirm the working
tree carries no private paths, personal vault content, or internal tooling
names — example content uses neutral placeholders (`Acme`, `Widget`) by
design. A quick sweep:

```bash
git grep -nE "/home/|/Users/" -- ':!*.md'   # stray absolute paths
```

To go public / push a release:

1. `git remote add origin git@github.com:lavallee/eno.git` (first time).
2. `git push -u origin main` and push tags.
3. Enable GitHub Pages on `main` / `docs`.
4. Publish the packages to PyPI (see the checklist above).
