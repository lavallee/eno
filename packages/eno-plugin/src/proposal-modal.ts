import { App, MarkdownView, Modal, Notice, Setting, TFile } from "obsidian";

export const PROPOSALS_FOLDER = "Eno Proposals";
interface Proposal { path: string; base: string; proposed: string }

export function parseProposal(raw: string): Proposal {
  const value: unknown = JSON.parse(raw);
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Proposal must be a JSON object.");
  const p = value as Record<string, unknown>;
  if (typeof p.path !== "string" || !p.path.trim() || typeof p.base !== "string" || typeof p.proposed !== "string") throw new Error("Proposal needs a vault-relative path, base text, and proposed text.");
  if (p.base === p.proposed) throw new Error("The proposal contains no changes.");
  return { path: p.path, base: p.base, proposed: p.proposed };
}

export class ProposalModal extends Modal {
  private proposal: Proposal | null = null;
  private proposalFile: TFile | null = null;
  private reviewEl!: HTMLElement;
  constructor(app: App, private target: MarkdownView) { super(app); }

  onOpen(): void {
    this.contentEl.createEl("h2", { text: "Review a note proposal" });
    this.contentEl.createEl("p", { text: "Choose a proposal for this note. The agent places proposals in your vault." });
    this.reviewEl = this.contentEl.createDiv();
    void this.list();
  }

  private async list(): Promise<void> {
    const targetPath = this.target.file?.path;
    const files = this.app.vault.getFiles().filter(f => f.parent?.path === PROPOSALS_FOLDER && f.extension === "md");
    const matches: { file: TFile; proposal: Proposal }[] = [];
    for (const file of files) {
      try {
        const proposal = parseProposal(await this.app.vault.read(file));
        if (proposal.path === targetPath) matches.push({ file, proposal });
      } catch { /* Ignore incomplete or unrelated files. */ }
    }
    if (!this.contentEl.isConnected) return;
    matches.sort((a, b) => b.file.stat.mtime - a.file.stat.mtime);
    if (!matches.length) {
      this.reviewEl.setText("No proposals found for this note. Ask your agent to prepare one, then open this command again.");
      return;
    }
    for (const match of matches) {
      new Setting(this.reviewEl).setName(match.file.basename).setDesc(new Date(match.file.stat.mtime).toLocaleString())
        .addButton(button => button.setButtonText("Review").onClick(() => this.review(match.file, match.proposal)));
    }
  }

  private review(file: TFile, proposal: Proposal): void {
    this.reviewEl.empty();
    try {
      if (!this.target.file || this.target.file.path !== proposal.path) throw new Error("Open the proposal's exact target note and try again.");
      if (this.target.editor.getValue() !== proposal.base) throw new Error("The note differs from the version the agent read. Ask for a fresh proposal.");
      this.proposal = proposal;
      this.proposalFile = file;
      this.reviewEl.createEl("p", { text: `Target: ${proposal.path}. Compare the complete current and proposed text below.` });
      this.addText("Current", proposal.base);
      this.addText("Proposed", proposal.proposed);
      new Setting(this.reviewEl).addButton(button => button.setButtonText("Apply proposal").setCta().onClick(() => { void this.apply(); }));
    } catch (error) {
      this.proposal = null;
      this.reviewEl.createEl("p", { text: error instanceof Error ? error.message : String(error), cls: "eno-proposal-error" });
    }
  }

  private addText(label: string, value: string): void {
    this.reviewEl.createEl("h3", { text: label });
    const area = this.reviewEl.createEl("textarea", { cls: "eno-proposal-version" });
    area.value = value;
    area.readOnly = true;
    area.setAttribute("aria-label", label + " note text");
  }

  private async apply(): Promise<void> {
    const p = this.proposal;
    const file = this.target.file;
    const editor = this.target.editor;
    if (!p || !file || file.path !== p.path || editor.getValue() !== p.base) {
      new Notice("Eno: note changed or closed. Request a fresh proposal.", 8000);
      this.close();
      return;
    }
    const last = editor.lastLine();
    editor.replaceRange(p.proposed, { line: 0, ch: 0 }, { line: last, ch: editor.getLine(last).length });
    const proposalFile = this.proposalFile;
    this.close();
    try {
      const archive = PROPOSALS_FOLDER + "/Applied";
      if (!this.app.vault.getAbstractFileByPath(archive)) await this.app.vault.createFolder(archive);
      if (proposalFile) await this.app.fileManager.renameFile(proposalFile, archive + "/" + proposalFile.name);
      new Notice("Eno: proposal applied and archived. You can undo it in the editor.");
    } catch {
      new Notice("Eno: proposal applied, but could not be archived.", 8000);
    }
  }
  onClose(): void { this.contentEl.empty(); }
}
