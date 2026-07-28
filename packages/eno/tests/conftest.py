"""Shared fixtures. Repo convention is inline tmp_path construction per test;
the flip vault is the one fixture worth centralizing (used across indexer,
garden, and queries tests).

The three OKF fixtures below (relative-link bundle, current-shape flip
notebook, every-portable-field bundle) are the interoperability corpus for
eno-as-generic-OKF-consumer: each is written out at test time so an indexed
copy is always disposable. Their content is invented; the shapes follow OKF
v0.2 §5-§6 and the flip profile."""

from pathlib import Path

import pytest


def make_flip_vault(root: Path) -> Path:
    """Two flip bundles (notebook + beat) with a colliding A1, a workspace
    handle table, and a vault note outside any bundle."""

    def w(rel: str, content: str) -> None:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)

    w(
        ".flip/workspace.toml",
        '[workspace]\nversion = "0.1"\n\n'
        '[notebooks]\nhosm = "research/hosm"\nfront = "areas/frontier"\n',
    )
    w(
        "research/hosm/index.md",
        '---\nokf_version: "0.4"\nflip: "0.4"\n---\n# HOSM\n',
    )
    w(
        "research/hosm/references/paper-alpha.md",
        "---\nid: A1\naliases: [A1]\n---\n# Paper Alpha\n",
    )
    w(
        "research/hosm/claims/claim-one.md",
        "---\nid: C1\n---\n# Claim One\n\n"
        "[[A1]] [[front:A1]] [[front#T2]] [[front:T9]] [[nope:A1]]\n",
    )
    w(
        "areas/frontier/index.md",
        '---\nokf_version: "0.4"\nflip_beat: "0.4"\n---\n# Frontier\n',
    )
    w(
        "areas/frontier/references/paper-beta.md",
        "---\nid: A1\naliases: [A1]\n---\n# Paper Beta\n",
    )
    w(
        "areas/frontier/threads/thread-two.md",
        "---\nid: T2\n---\n# Thread Two\n\n[[A1]]\n",
    )
    w("Notes.md", "# Notes\n\n[[hosm:C1]] [[A1]] [[A33]]\n")
    return root


@pytest.fixture()
def flip_vault(tmp_path: Path) -> Path:
    return make_flip_vault(tmp_path)


def _writer(root: Path):
    def w(rel: str, content: str) -> None:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)

    return w


# ---- OKF interoperability fixtures ----------------------------------------
#
# Each `EXPECTED_*_EDGES` constant is the fixture's own answer key: every
# internal markdown edge the bundle intends to resolve, as
# (src_path, target_text) -> target_path. Anything the fixture means to leave
# dangling is listed separately, so "100% of expected edges resolve" and
# "broken links stay visible" are both checkable without re-deriving the graph
# from the prose.


def make_okf_relative_vault(root: Path) -> Path:
    """A relative-link OKF bundle: one bundle root, six concept pages, a
    directory listing, an anchored link, a bundle-absolute link, and one link
    to a page nobody has written yet."""
    w = _writer(root)

    w(
        "knowledge/index.md",
        '---\nokf_version: "0.2"\n---\n'
        "# Warehouse knowledge\n\n"
        "* [Orders](tables/orders.md) - one row per placed order\n"
        "* [Customers](tables/customers.md) - one row per account\n"
        "* [Fill rate](metrics/fill-rate.md) - share of orders shipped complete\n"
        "* [Backfill playbook](playbooks/backfill.md) - what to run after a late load\n"
        "* [Glossary](references/glossary.md) - shared terms\n",
    )
    w(
        "knowledge/tables/index.md",
        "# Tables\n\n"
        "* [Orders](orders.md) - one row per placed order\n"
        "* [Customers](customers.md) - one row per account\n",
    )
    w(
        "knowledge/tables/orders.md",
        "---\ntype: Warehouse Table\ntitle: Orders\n"
        "description: One row per placed order.\n---\n"
        "# Schema\n\n"
        "Each row carries an account key joined to [customers](customers.md).\n\n"
        "The [fill rate metric](../metrics/fill-rate.md) is computed from this table.\n\n"
        "Column meanings follow the [glossary](/references/glossary.md).\n",
    )
    w(
        "knowledge/tables/customers.md",
        "---\ntype: Warehouse Table\ntitle: Customers\n---\n"
        "# Customers\n\n"
        "One row per account. See the [orders schema](orders.md#schema) for the join key.\n\n"
        "Account age feeds [lead time](../metrics/lead-time.md), which nobody has "
        "written yet.\n",
    )
    w(
        "knowledge/metrics/fill-rate.md",
        "---\ntype: Metric\ntitle: Fill rate\n---\n"
        "# Definition\n\n"
        "Share of [orders](../tables/orders.md) shipped complete on the first attempt.\n\n"
        "When it dips, run the [backfill playbook](../playbooks/backfill.md).\n\n"
        "Background reading: [the vendor's note](https://example.invalid/fill-rate) and\n"
        "`[the inline-code decoy](decoy.md)`, neither of which is a bundle edge.\n\n"
        "![Trend sketch](../assets/fill-rate.png)\n\n"
        "```markdown\n[fenced decoy](fenced.md)\n```\n",
    )
    w(
        "knowledge/playbooks/backfill.md",
        "---\ntype: Playbook\ntitle: Backfill after a late load\n---\n"
        "# Steps\n\n"
        "1. Confirm the late partition in [the orders table](../tables/orders.md).\n"
        "2. Recompute [fill rate](../metrics/fill-rate.md) for the affected days.\n"
        "3. Skim [all tables](../tables/) for anything else downstream.\n",
    )
    w(
        "knowledge/references/glossary.md",
        "---\ntype: Reference\ntitle: Glossary\n---\n"
        "# Glossary\n\n"
        "Terms used across [the bundle index](../index.md).\n",
    )
    return root


EXPECTED_OKF_RELATIVE_EDGES = {
    ("knowledge/index.md", "tables/orders.md"): "knowledge/tables/orders.md",
    ("knowledge/index.md", "tables/customers.md"): "knowledge/tables/customers.md",
    ("knowledge/index.md", "metrics/fill-rate.md"): "knowledge/metrics/fill-rate.md",
    ("knowledge/index.md", "playbooks/backfill.md"): "knowledge/playbooks/backfill.md",
    ("knowledge/index.md", "references/glossary.md"): "knowledge/references/glossary.md",
    ("knowledge/tables/index.md", "orders.md"): "knowledge/tables/orders.md",
    ("knowledge/tables/index.md", "customers.md"): "knowledge/tables/customers.md",
    ("knowledge/tables/orders.md", "customers.md"): "knowledge/tables/customers.md",
    ("knowledge/tables/orders.md", "../metrics/fill-rate.md"): (
        "knowledge/metrics/fill-rate.md"
    ),
    # Bundle-absolute: resolves against the bundle root, not the vault root.
    ("knowledge/tables/orders.md", "/references/glossary.md"): (
        "knowledge/references/glossary.md"
    ),
    # Anchored: the anchor is recorded, the path still resolves.
    ("knowledge/tables/customers.md", "orders.md"): "knowledge/tables/orders.md",
    ("knowledge/metrics/fill-rate.md", "../tables/orders.md"): (
        "knowledge/tables/orders.md"
    ),
    ("knowledge/metrics/fill-rate.md", "../playbooks/backfill.md"): (
        "knowledge/playbooks/backfill.md"
    ),
    ("knowledge/playbooks/backfill.md", "../tables/orders.md"): (
        "knowledge/tables/orders.md"
    ),
    ("knowledge/playbooks/backfill.md", "../metrics/fill-rate.md"): (
        "knowledge/metrics/fill-rate.md"
    ),
    # Directory link: falls through to that directory's index.md.
    ("knowledge/playbooks/backfill.md", "../tables/"): "knowledge/tables/index.md",
    ("knowledge/references/glossary.md", "../index.md"): "knowledge/index.md",
}

# Deliberately dangling — legal OKF (§6.1), visible but non-fatal.
EXPECTED_OKF_RELATIVE_DANGLING = {
    ("knowledge/tables/customers.md", "../metrics/lead-time.md"),
}


@pytest.fixture()
def okf_relative_vault(tmp_path: Path) -> Path:
    return make_okf_relative_vault(tmp_path)


def make_flip_notebook_vault(root: Path) -> Path:
    """Two current-shape flip notebooks in one workspace.

    Exercises bare ids, a workspace-qualified alias, claims carrying OKF
    `sources` entries plus footnote links, and one deliberately dangling
    citation. Both notebooks hold an `A1`, so a bare id must never leak across
    the notebook boundary."""
    w = _writer(root)

    w(
        ".flip/workspace.toml",
        '[workspace]\nversion = "0.1"\n\n'
        '[notebooks]\nroofs = "notebooks/roof-coatings"\n'
        'transit = "notebooks/transit-dwell"\n',
    )

    # --- notebook one: roof coatings -------------------------------------
    w(
        "notebooks/roof-coatings/index.md",
        "---\n"
        "okf_version: '0.2'\n"
        "flip: '0.14'\n"
        "slug: roof-coatings\n"
        "title: Do reflective roof coatings lower indoor peak temperature?\n"
        "kind: lit-review\n"
        "status: active\n"
        "---\n"
        "# Do reflective roof coatings lower indoor peak temperature?\n\n"
        "* [References](references/) - 2 captured sources\n"
        "* [Claims](claims/) - 2 claims with status and citations\n"
        "* [Questions](questions/) - 1 open question\n",
    )
    w(
        "notebooks/roof-coatings/references/index.md",
        "# References\n\n"
        "* [A1](field-trial-summer-attic.md) - attic temperature field trial\n"
        "* [A2](municipal-retrofit-report.md) - municipal retrofit report\n",
    )
    w(
        "notebooks/roof-coatings/references/field-trial-summer-attic.md",
        "---\n"
        "type: Source\n"
        "id: A1\n"
        "aliases:\n- A1\n- roofs:A1\n"
        "title: Attic temperature field trial, twelve houses\n"
        "resource: https://example.invalid/attic-field-trial\n"
        "grade: B\n"
        "independence: independent\n"
        "status: captured\n"
        "generated:\n  by: agent:scribe\n  at: '2026-05-02T09:15:00Z'\n"
        "---\n"
        "# Attic temperature field trial, twelve houses\n\n"
        "Twelve single-storey houses, instrumented for one cooling season.\n",
    )
    w(
        "notebooks/roof-coatings/references/municipal-retrofit-report.md",
        "---\n"
        "type: Source\n"
        "id: A2\n"
        "aliases:\n- A2\n- roofs:A2\n"
        "title: Municipal retrofit programme report\n"
        "resource: https://example.invalid/retrofit-report\n"
        "grade: C\n"
        "independence: self-reported\n"
        "status: captured\n"
        "generated:\n  by: agent:scribe\n  at: '2026-05-02T09:20:00Z'\n"
        "---\n"
        "# Municipal retrofit programme report\n\n"
        "Programme office's own account of 400 retrofitted roofs.\n",
    )
    w(
        "notebooks/roof-coatings/claims/index.md",
        "# Claims\n\n"
        "* [C1](coatings-lower-attic-peak.md) - coatings lowered attic peak temperature\n"
        "* [C2](occupant-comfort-unmeasured.md) - occupant comfort went unmeasured\n",
    )
    w(
        "notebooks/roof-coatings/claims/coatings-lower-attic-peak.md",
        "---\n"
        "type: Claim\n"
        "id: C1\n"
        "aliases:\n- C1\n"
        "description: Reflective coatings lowered measured attic peak temperature\n"
        "status: verified\n"
        "load_bearing: true\n"
        "sources:\n"
        "- id: A1\n"
        "  resource: /references/field-trial-summer-attic.md\n"
        "  title: Attic temperature field trial, twelve houses\n"
        "- id: A2\n"
        "  resource: /references/municipal-retrofit-report.md\n"
        "  title: Municipal retrofit programme report\n"
        "independent_corroboration: 1\n"
        "first_asserted: '2026-05-03'\n"
        "generated:\n  by: agent:scribe\n  at: '2026-05-03T11:00:00Z'\n"
        "verified:\n"
        "- by: human:dana\n"
        "  at: '2026-05-04T08:00:00Z'\n"
        "  method: independent-sources\n"
        "  against:\n  - A2\n"
        "---\n\n"
        "Reflective coatings lowered measured attic peak temperature in both "
        "reports[^A1][^A2]\n\n"
        "Related thread in the neighbouring notebook: [[transit:C1]].\n\n"
        "[^A1]: [Attic temperature field trial](../references/field-trial-summer-attic.md)\n"
        "[^A2]: [Municipal retrofit report](../references/municipal-retrofit-report.md)\n",
    )
    w(
        "notebooks/roof-coatings/claims/occupant-comfort-unmeasured.md",
        "---\n"
        "type: Claim\n"
        "id: C2\n"
        "aliases:\n- C2\n"
        "description: Neither report measured occupant comfort directly\n"
        "status: asserted\n"
        "load_bearing: false\n"
        "sources:\n"
        "- id: A1\n"
        "  resource: /references/field-trial-summer-attic.md\n"
        "  title: Attic temperature field trial, twelve houses\n"
        "- id: A7\n"
        "first_asserted: '2026-05-03'\n"
        "generated:\n  by: agent:scribe\n  at: '2026-05-03T11:05:00Z'\n"
        "---\n\n"
        "Neither report measured occupant comfort directly[^A1][^A7]\n\n"
        "Bare id in prose resolves inside this notebook: [[A1]].\n\n"
        "[^A1]: [Attic temperature field trial](../references/field-trial-summer-attic.md)\n"
        "[^A7]: [Comfort survey, not yet captured](../references/comfort-survey.md)\n",
    )
    w(
        "notebooks/roof-coatings/questions/index.md",
        "# Questions\n\n"
        "* [Q1](does-effect-persist-in-humid-climates.md) - does the effect persist "
        "in humid climates?\n",
    )
    w(
        "notebooks/roof-coatings/questions/does-effect-persist-in-humid-climates.md",
        "---\n"
        "type: Question\n"
        "id: Q1\n"
        "aliases:\n- Q1\n"
        "description: Does the attic-temperature effect persist in humid climates?\n"
        "status: open\n"
        "generated:\n  by: agent:scribe\n  at: '2026-05-03T11:10:00Z'\n"
        "---\n\n"
        "Both reports come from dry-summer regions; see [C1](../claims/"
        "coatings-lower-attic-peak.md).\n",
    )

    # --- notebook two: transit dwell (its own A1 and C1) ------------------
    w(
        "notebooks/transit-dwell/index.md",
        "---\n"
        "okf_version: '0.2'\n"
        "flip: '0.14'\n"
        "slug: transit-dwell\n"
        "title: What drives platform dwell time?\n"
        "kind: scout\n"
        "status: active\n"
        "---\n"
        "# What drives platform dwell time?\n\n"
        "* [References](references/) - 1 captured source\n",
    )
    w(
        "notebooks/transit-dwell/references/index.md",
        "# References\n\n* [A1](door-cycle-timings.md) - door cycle timings\n",
    )
    w(
        "notebooks/transit-dwell/references/door-cycle-timings.md",
        "---\n"
        "type: Source\n"
        "id: A1\n"
        "aliases:\n- A1\n- transit:A1\n"
        "title: Door cycle timings, three stations\n"
        "resource: https://example.invalid/door-cycles\n"
        "grade: B\n"
        "status: captured\n"
        "generated:\n  by: agent:scribe\n  at: '2026-05-05T14:00:00Z'\n"
        "---\n"
        "# Door cycle timings, three stations\n\n"
        "Manual stopwatch counts over four weekday peaks.\n",
    )
    w(
        "notebooks/transit-dwell/claims/index.md",
        "# Claims\n\n* [C1](door-cycles-dominate-dwell.md) - door cycles dominate dwell\n",
    )
    w(
        "notebooks/transit-dwell/claims/door-cycles-dominate-dwell.md",
        "---\n"
        "type: Claim\n"
        "id: C1\n"
        "aliases:\n- C1\n"
        "description: Door cycle duration dominates measured platform dwell\n"
        "status: asserted\n"
        "load_bearing: true\n"
        "sources:\n"
        "- id: A1\n"
        "  resource: /references/door-cycle-timings.md\n"
        "  title: Door cycle timings, three stations\n"
        "first_asserted: '2026-05-05'\n"
        "generated:\n  by: agent:scribe\n  at: '2026-05-05T14:30:00Z'\n"
        "---\n\n"
        "Door cycle duration dominates measured platform dwell[^A1]\n\n"
        "[^A1]: [Door cycle timings](../references/door-cycle-timings.md)\n",
    )
    return root


@pytest.fixture()
def flip_notebook_vault(tmp_path: Path) -> Path:
    return make_flip_notebook_vault(tmp_path)


def make_okf_portable_vault(root: Path) -> Path:
    """A minimal OKF v0.2 bundle exercising every portable trust field, a bare
    `verified` mapping, unknown extension keys, and a concept carrying nothing
    but `type`."""
    w = _writer(root)

    w(
        "bundle/index.md",
        '---\nokf_version: "0.2"\n---\n'
        "# Portable field sampler\n\n"
        "* [Shipment cost](metrics/shipment-cost.md) - the narrated metric\n"
        "* [Cost computation](computations/shipment-cost.md) - the sanctioned computation\n"
        "* [Allocation policy](references/allocation-policy.md) - the policy of record\n"
        "* [Unprovenanced claim](claims/margin-improved.md) - a claim with no provenance\n",
    )
    w(
        "bundle/metrics/shipment-cost.md",
        "---\n"
        "type: Metric\n"
        "title: Shipment cost per parcel\n"
        "description: Fully loaded cost of moving one parcel.\n"
        "resource: https://example.invalid/warehouse/metrics/shipment-cost\n"
        "tags: [logistics, cost]\n"
        "status: stable\n"
        "stale_after: 2020-01-01\n"
        "generated: { by: costing_agent/v3, at: 2026-07-01T10:00:00Z }\n"
        "verified:\n"
        "  - { by: human:rivera, at: 2026-06-10T09:00:00Z }\n"
        "  - { by: process:nightly-costing, at: 2026-06-11T02:00:00Z }\n"
        "sources:\n"
        "  - id: alloc-policy\n"
        "    resource: /references/allocation-policy.md\n"
        "    title: Cost allocation policy\n"
        "    author: team:logistics\n"
        "    last_modified: 2026-04-02\n"
        "  - id: carrier-feed\n"
        "    resource: https://example.invalid/carrier-feed\n"
        "    title: Carrier rate feed\n"
        "    usage_count: 1200\n"
        "  - id: parcel-panel\n"
        "    resource: all parcels handled at the north depot\n"
        "    title: North depot parcel population\n"
        "  - id: retired-memo\n"
        "    resource: /references/retired-memo.md\n"
        "    title: Retired costing memo\n"
        "usage_window: { from: 2026-06-01, to: 2026-06-30 }\n"
        "x_department: logistics\n"
        "review_board:\n"
        "  chair: human:rivera\n"
        "  cadence: quarterly\n"
        "---\n"
        "# Definition\n\n"
        "Fully loaded cost per parcel, per the [allocation policy]"
        "(/references/allocation-policy.md).[^alloc-policy]\n\n"
        "Computed by [the cost computation](../computations/shipment-cost.md).\n\n"
        "[^alloc-policy]: Cost allocation policy\n",
    )
    w(
        "bundle/computations/shipment-cost.md",
        "---\n"
        "type: Attested Computation\n"
        "title: Shipment cost per parcel\n"
        "status: draft\n"
        "runtime: warehouse-sql\n"
        "parameters:\n"
        "  - { name: month, type: string, required: true }\n"
        "executor:\n"
        "  resource: references/runners/warehouse-sql.md\n"
        "  receipt: [run_id, executed_sql, result]\n"
        "attester:\n"
        "  resource: references/attesters/shipment-cost.py\n"
        "generated: { by: costing_agent/v3, at: 2026-06-28T14:00:00Z }\n"
        "verified: { by: process:nightly-costing, at: 2026-06-29T02:00:00Z }\n"
        "stale_after: 2999-12-31\n"
        "sources:\n"
        "  - id: alloc-policy\n"
        "    resource: /references/allocation-policy.md\n"
        "    title: Cost allocation policy\n"
        "---\n"
        "# Computation\n\n"
        "    SELECT total_cost / parcels FROM depot_month WHERE month = :month\n\n"
        "Narrated by [the metric](../metrics/shipment-cost.md).\n",
    )
    w(
        "bundle/references/allocation-policy.md",
        "---\ntype: Reference\ntitle: Cost allocation policy\n---\n"
        "# Cost allocation policy\n\n"
        "How depot overhead is apportioned across parcels.\n",
    )
    w(
        "bundle/claims/margin-improved.md",
        "---\ntype: Claim\ntitle: Margin improved after the depot move\n---\n"
        "# Margin improved after the depot move\n\n"
        "Asserted in passing, with nothing behind it.\n",
    )
    return root


@pytest.fixture()
def okf_portable_vault(tmp_path: Path) -> Path:
    return make_okf_portable_vault(tmp_path)
