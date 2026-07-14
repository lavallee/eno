"""SQLite schema for the vault index.

Five tables: notes, headings, links, tags, aliases. Backlinks are a query, not a table.
Schema version pinned in state.json; on bump, drop + reindex (cheap at vault scale).
"""

import sqlite3

SCHEMA_VERSION = 1

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS notes (
    path TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    word_count INTEGER NOT NULL DEFAULT 0,
    mtime REAL NOT NULL,
    content_hash TEXT NOT NULL,
    frontmatter_json TEXT NOT NULL DEFAULT '{}',
    origin TEXT,
    stage TEXT,
    type TEXT,
    created_at TEXT,
    updated_at TEXT,
    kind TEXT NOT NULL DEFAULT 'md',
    has_canvas INTEGER NOT NULL DEFAULT 0,
    indexed_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS headings (
    path TEXT NOT NULL REFERENCES notes(path) ON DELETE CASCADE,
    level INTEGER NOT NULL,
    text TEXT NOT NULL,
    line_no INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS links (
    src_path TEXT NOT NULL REFERENCES notes(path) ON DELETE CASCADE,
    target_text TEXT NOT NULL,
    target_path TEXT,
    alias TEXT,
    line_no INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS tags (
    path TEXT NOT NULL REFERENCES notes(path) ON DELETE CASCADE,
    tag TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS aliases (
    path TEXT NOT NULL REFERENCES notes(path) ON DELETE CASCADE,
    alias TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_links_target ON links(target_path);
CREATE INDEX IF NOT EXISTS idx_links_src ON links(src_path);
CREATE INDEX IF NOT EXISTS idx_tags_tag ON tags(tag);
CREATE INDEX IF NOT EXISTS idx_aliases_alias_lower ON aliases(LOWER(alias));
CREATE INDEX IF NOT EXISTS idx_headings_path ON headings(path);
"""


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA_SQL)
    conn.commit()
