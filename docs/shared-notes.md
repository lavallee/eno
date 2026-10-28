# Shared notes with an agent

A note can be the shared working surface: a person and an agent both read it,
update it, and leave decisions visible in ordinary Markdown. Eno helps locate
and understand the canonical note; the calling agent does the interpretation.
This is a workflow, not a background agent or a real-time collaboration system.

## First pass

1. Locate the note with Eno, then read the current full text through the owning
   vault interface. Confirm the vault and exact path; an index excerpt may be
   stale or incomplete. Obsidian's CLI (`obsidian vault=<name> read path=<path>`)
   is one option when Obsidian is running and CLI access is enabled.
2. Distill a short goal and group actionable items as Markdown checkboxes.
   Separate open decisions and speculative ideas from tasks. Do not invent
   owners, deadlines, completion status, or certainty. Label extracted tasks as
   proposals when the source does not establish their current status.
3. Preserve the source transcript. Add the working material to the canonical
   note when asked to clean it up, rather than creating a competing task list.
   Preserve existing frontmatter, links, task statuses and the person's edits.
4. Re-read before writing and stop if the source has changed; reconcile against
   the new version. Verify the saved note and, where available, that Obsidian
   sees its checkboxes (`obsidian tasks path=<path> todo`).

For follow-up work, read the current note again, update only the relevant work,
keep completed checkboxes and decisions legible, and report what changed. The
note is a shared record; it does not itself dispatch work or sync tasks to a
separate tracker.

## Review an agent proposal in Obsidian

The agent queues a proposal through the running Obsidian app, using
`scripts/propose_note.py --vault VAULT_NAME --path NOTE_PATH --base BASE_FILE
--proposed REPLACEMENT_FILE`. The files contain the exact complete source and
replacement text. The script checks the current saved vault text and creates a
proposal under `Eno Proposals/`; no JSON needs to be copied by the person.
Use `scripts/read_note.py --vault VAULT_NAME --path NOTE_PATH --output
BASE_FILE` to capture the exact saved source, including final newlines; CLI
display output may add a newline. The script requires Obsidian's CLI and
running app, and refuses a changed source. Never queue private content without
the owner's authorization.

Open the target note in editing mode and run **Eno: Review a note proposal**.
Choose the proposal, compare both versions, and apply it. If a proposal arrives
while its target is active, the plugin displays a notice. Applied proposals are
moved to `Eno Proposals/Applied/` as a receipt. The plugin checks the exact
path and editor text at review and again at apply; if either changes, ask the
agent for a fresh proposal. This protects against edits reflected in that
editor; it is not a distributed lock against another device or a filesystem
change that has not yet reached Obsidian.

The proposal is vault-local and the plugin does not generate it or launch an
agent. Review currently shows complete versions rather than a highlighted diff,
so long notes can be cumbersome to compare. Proposal files contain both versions
of the note and follow the vault's existing sync and access settings.

## Choosing a write surface

- Eno MCP currently supports creating and appending to notes. Use these where
  their semantics fit; its indexed `eno_note` is not a full-text editing API.
- The Obsidian CLI can read, prepend and append through the running app. A
  read followed by a CLI write is **not** an atomic compare-and-swap: another
  edit can occur between the two. Use it for a bounded, coordinated initial
  addition, not as a promise of conflict-free concurrent editing. Never use
  `create overwrite` as a substitute for a guarded edit.
- The Eno plugin review command checks and edits the active source editor. For
  background edits, a future integration should use Obsidian’s `Vault.process`
  to compare and update inside its callback.

Respect the vault owner's write permissions and any read-only estate policy.
If the note cannot be written, provide the proposed changes for review instead
of silently routing around the restriction. For Flip-owned notes, use their
owning notebook workflow.
