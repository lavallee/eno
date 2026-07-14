// Right-pane view: service status + latest garden-report counts + action buttons.
// Reads counts from the report file's frontmatter (populated by Python's
// render_garden_report) so the plugin doesn't need to parse markdown by hand.

import { ItemView, TFile, WorkspaceLeaf } from "obsidian";
import type EnoPlugin from "./main";
import type { GardenCounts } from "./types";

export const VIEW_TYPE_ENO_HEALTH = "eno-health";

export class HealthView extends ItemView {
  private plugin: EnoPlugin;

  constructor(leaf: WorkspaceLeaf, plugin: EnoPlugin) {
    super(leaf);
    this.plugin = plugin;
  }

  getViewType(): string {
    return VIEW_TYPE_ENO_HEALTH;
  }

  getDisplayText(): string {
    return "Eno: vault health";
  }

  getIcon(): string {
    return "flower";
  }

  async onOpen(): Promise<void> {
    await this.refresh();
  }

  async onClose(): Promise<void> {}

  async refresh(): Promise<void> {
    const root = this.containerEl.children[1] as HTMLElement;
    root.empty();
    root.addClass("eno-view");

    root.createEl("h3", { text: "Eno — Vault Health" });

    // Service status block
    const statusEl = root.createEl("div", { cls: "eno-status" });
    try {
      const health = await this.plugin.api.health();
      const ok = health.ok ? "✓ ok" : "✗ down";
      statusEl.createEl("p", { text: `service: ${ok}` });
      const where =
        health.vault ?? health.service_url ?? this.plugin.settings.serviceUrl;
      statusEl.createEl("p", { text: where, cls: "eno-meta" });
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      statusEl.createEl("p", {
        text: `service: unreachable`,
        cls: "eno-error",
      });
      statusEl.createEl("p", { text: msg, cls: "eno-meta" });
    }

    // Latest garden report counts
    const latest = this.findLatestReport("garden");
    const reportEl = root.createEl("div", { cls: "eno-report" });
    if (!latest) {
      reportEl.createEl("p", {
        text: "no garden report yet — run \"Garden now\" below",
        cls: "eno-meta",
      });
    } else {
      const counts = this.readCounts(latest);
      reportEl.createEl("p", {
        text: `last garden: ${latest.basename}`,
        cls: "eno-meta",
      });
      const list = reportEl.createEl("ul");
      if (!counts) {
        list.createEl("li", { text: "(report has no parseable frontmatter)" });
      } else {
        list.createEl("li", { text: `resurfacing:        ${counts.resurfacing}` });
        list.createEl("li", { text: `concept candidates: ${counts.concepts}` });
        list.createEl("li", { text: `drift candidates:   ${counts.drift}` });
        list.createEl("li", { text: `duplicates:         ${counts.duplicates}` });
        list.createEl("li", { text: `stubs:              ${counts.stubs}` });
        list.createEl("li", { text: `stale:              ${counts.stale}` });
      }
    }

    // Latest hygiene proposals
    const hyg = this.findLatestReport("hygiene-proposals");
    if (hyg) {
      const counts = this.readHygieneCounts(hyg);
      const hygEl = root.createEl("div", { cls: "eno-report" });
      hygEl.createEl("p", {
        text: `last hygiene proposals: ${hyg.basename}`,
        cls: "eno-meta",
      });
      if (counts) {
        const list = hygEl.createEl("ul");
        list.createEl("li", { text: `proposals:    ${counts.proposals}` });
        list.createEl("li", { text: `eligible:     ${counts.eligible}` });
        list.createEl("li", { text: `total notes:  ${counts.total_notes}` });
      }
    }

    // Action buttons
    const actions = root.createEl("div", { cls: "eno-actions" });

    const gardenBtn = actions.createEl("button", { text: "Garden now" });
    gardenBtn.addEventListener("click", async () => {
      gardenBtn.disabled = true;
      gardenBtn.setText("gardening…");
      await this.plugin.gardenNow();
      gardenBtn.disabled = false;
      gardenBtn.setText("Garden now");
      await this.refresh();
    });

    const openGarden = actions.createEl("button", {
      text: "Open latest garden report",
    });
    openGarden.addEventListener("click", () => {
      this.plugin.openLatestReport("garden");
    });

    const openHyg = actions.createEl("button", {
      text: "Open latest hygiene proposals",
    });
    openHyg.addEventListener("click", () => {
      this.plugin.openLatestReport("hygiene-proposals");
    });
  }

  private findLatestReport(
    kind: "garden" | "hygiene-proposals"
  ): TFile | null {
    const folder = this.plugin.settings.reportsFolder;
    const all = this.plugin.app.vault
      .getFiles()
      .filter(
        (f) => f.path.startsWith(folder + "/") && f.path.endsWith(`-${kind}.md`)
      );
    if (all.length === 0) return null;
    all.sort((a, b) => b.path.localeCompare(a.path));
    return all[0];
  }

  private readCounts(file: TFile): GardenCounts | null {
    const cache = this.plugin.app.metadataCache.getFileCache(file);
    const counts = cache?.frontmatter?.counts as
      | Partial<GardenCounts>
      | undefined;
    if (!counts) return null;
    return {
      resurfacing: counts.resurfacing ?? 0,
      concepts: counts.concepts ?? 0,
      drift: counts.drift ?? 0,
      duplicates: counts.duplicates ?? 0,
      stubs: counts.stubs ?? 0,
      stale: counts.stale ?? 0,
    };
  }

  private readHygieneCounts(file: TFile): {
    total_notes: number;
    eligible: number;
    proposals: number;
  } | null {
    const cache = this.plugin.app.metadataCache.getFileCache(file);
    const counts = cache?.frontmatter?.counts as
      | { total_notes?: number; eligible?: number; proposals?: number }
      | undefined;
    if (!counts) return null;
    return {
      total_notes: counts.total_notes ?? 0,
      eligible: counts.eligible ?? 0,
      proposals: counts.proposals ?? 0,
    };
  }
}
