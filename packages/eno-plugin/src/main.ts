import { MarkdownView, Notice, Plugin, TFile, WorkspaceLeaf } from "obsidian";
import { parseProposal, ProposalModal, PROPOSALS_FOLDER } from "./proposal-modal";
import { EnoApi } from "./api";
import { HealthView, VIEW_TYPE_ENO_HEALTH } from "./health-view";
import {
  DEFAULT_SETTINGS,
  EnoSettings,
  EnoSettingsTab,
} from "./settings";

export default class EnoPlugin extends Plugin {
  settings!: EnoSettings;
  api!: EnoApi;

  async onload(): Promise<void> {
    await this.loadSettings();
    this.api = new EnoApi(() => this.settings.serviceUrl);

    this.registerView(
      VIEW_TYPE_ENO_HEALTH,
      (leaf) => new HealthView(leaf, this)
    );

    this.addRibbonIcon("flower", "Eno: open vault health", () => {
      void this.activateHealthView();
    });

    this.addCommand({
      id: "open-vault-health",
      name: "Open vault health view",
      callback: () => void this.activateHealthView(),
    });

    this.addCommand({
      id: "garden-now",
      name: "Garden now",
      callback: () => void this.gardenNow(),
    });

    this.addCommand({
      id: "open-latest-garden-report",
      name: "Open latest garden report",
      callback: () => void this.openLatestReport("garden"),
    });

    this.addCommand({
      id: "open-latest-hygiene-proposals",
      name: "Open latest hygiene proposals",
      callback: () => void this.openLatestReport("hygiene-proposals"),
    });

    this.addCommand({
      id: "show-active-note-neighbors",
      name: "Show neighbors of active note",
      checkCallback: (checking: boolean) => {
        const file = this.app.workspace.getActiveFile();
        if (!file) return false;
        if (!checking) void this.showNeighbors(file);
        return true;
      },
    });

    this.addCommand({
      id: "review-note-proposal",
      name: "Review a note proposal",
      checkCallback: (checking: boolean) => {
        const view = this.app.workspace.getActiveViewOfType(MarkdownView);
        if (!view || !view.file || view.getMode() !== "source") return false;
        if (!checking) new ProposalModal(this.app, view).open();
        return true;
      },
    });

    this.registerEvent(this.app.vault.on("create", (file) => {
      if (!(file instanceof TFile) || file.parent?.path !== PROPOSALS_FOLDER || file.extension !== "md") return;
      void this.app.vault.read(file).then(raw => {
        try {
          const proposal = parseProposal(raw);
          if (this.app.workspace.getActiveFile()?.path === proposal.path) {
            new Notice("Eno: a proposal is ready. Run Review a note proposal.", 10000);
          }
        } catch { /* A non-proposal file needs no notification. */ }
      });
    }));

    this.addSettingTab(new EnoSettingsTab(this.app, this));
  }

  onunload(): void {
    this.app.workspace.detachLeavesOfType(VIEW_TYPE_ENO_HEALTH);
  }

  async loadSettings(): Promise<void> {
    this.settings = Object.assign(
      {},
      DEFAULT_SETTINGS,
      await this.loadData()
    );
  }

  async saveSettings(): Promise<void> {
    await this.saveData(this.settings);
  }

  async activateHealthView(): Promise<void> {
    const existing = this.app.workspace.getLeavesOfType(VIEW_TYPE_ENO_HEALTH);
    if (existing.length > 0) {
      this.app.workspace.revealLeaf(existing[0]);
      return;
    }
    const right = this.app.workspace.getRightLeaf(false);
    if (!right) return;
    await right.setViewState({ type: VIEW_TYPE_ENO_HEALTH, active: true });
    this.app.workspace.revealLeaf(right);
  }

  async gardenNow(): Promise<void> {
    new Notice("Eno: gardening…");
    try {
      const report = await this.api.garden();
      new Notice(
        `Eno garden — ${report.resurfacing.length} resurfacing, ` +
          `${report.concepts.length} concepts, ` +
          `${report.drift.length} drift, ` +
          `${report.duplicates.length} dupes`,
        8000
      );
      this.refreshOpenHealthViews();
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      new Notice(`Eno garden failed: ${msg}`, 10000);
    }
  }

  async openLatestReport(
    kind: "garden" | "hygiene-proposals"
  ): Promise<void> {
    const folder = this.settings.reportsFolder;
    const all = this.app.vault
      .getFiles()
      .filter(
        (f) => f.path.startsWith(folder + "/") && f.path.endsWith(`-${kind}.md`)
      );
    if (all.length === 0) {
      new Notice(`Eno: no ${kind} reports in ${folder}/`);
      return;
    }
    all.sort((a, b) => b.path.localeCompare(a.path));
    const newest = all[0];
    const leaf = this.app.workspace.getLeaf(false);
    await leaf.openFile(newest);
  }

  async showNeighbors(file: TFile): Promise<void> {
    try {
      const n = await this.api.neighbors(file.path);
      new Notice(
        `Eno: [[${file.basename}]] — ${n.backlinks.length} backlinks, ` +
          `${n.outbound.length} outbound`,
        8000
      );
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      new Notice(`Eno neighbors failed: ${msg}`, 8000);
    }
  }

  private refreshOpenHealthViews(): void {
    for (const leaf of this.app.workspace.getLeavesOfType(VIEW_TYPE_ENO_HEALTH)) {
      const view = leaf.view as HealthView;
      void view.refresh();
    }
  }
}
