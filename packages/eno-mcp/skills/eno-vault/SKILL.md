---
name: eno-vault
description: Ground questions, synthesis, gardening, and note writes in a connected Eno vault or Flip-notebook estate. Use when Eno MCP tools are available and the task depends on indexed knowledge, link meaning, note ownership, or provenance-aware writeback.
---

# Work from the Eno vault

Ground vault-dependent claims in Eno results and name the supporting note paths.
Search or retrieve before filling gaps from general knowledge. Read in two phases:
locate the relevant notes, then inspect only the promising notes or neighborhoods.
For a cross-project topic, search body text as well as titles before creating a
note or notebook; inspect the strongest overlaps rather than assuming the idea is
new. A returned `bundle_path` names the owning Flip notebook.

Preserve Eno's domain distinction: `eno_concepts` returns intentional groundwork
for possible notes, while `eno_drift` returns likely link defects. Never turn a
concept candidate into a cleanup finding merely because its target does not yet
exist.

Before writing, find the canonical home and extend it when appropriate. Create a
new note only when none fits. Preserve agent authorship on new notes, and surface
ambiguity before writing. If Eno reports a read-only estate, do not use its write
tools; write through the owning notebook's repo and Flip workflow instead.

For collaborative cleanup of an existing note, read the current full source,
preserve it, and distinguish proposed tasks from decisions and known status.
Re-read before writing and verify afterward; a CLI read followed by a write is
not an atomic conflict check. See the repository guide `docs/shared-notes.md`
when available.

For Eno plugin review, queue the proposal through the running Obsidian app
using `scripts/propose_note.py` in the Eno checkout; see `docs/shared-notes.md`.
Provide the exact full source and replacement as files, preserving frontmatter,
source text, and existing status as appropriate. Tell the person a proposal is
ready in Eno: Review a note proposal; do not ask them to copy JSON. If the note
changed, read it again and regenerate the proposal.
