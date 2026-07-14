import { App, PluginSettingTab, Setting } from "obsidian";
import type EnoPlugin from "./main";

export interface EnoSettings {
  serviceUrl: string;
  reportsFolder: string;
}

export const DEFAULT_SETTINGS: EnoSettings = {
  serviceUrl: "http://127.0.0.1:7891",
  reportsFolder: "9 Vault Health",
};

export class EnoSettingsTab extends PluginSettingTab {
  plugin: EnoPlugin;

  constructor(app: App, plugin: EnoPlugin) {
    super(app, plugin);
    this.plugin = plugin;
  }

  display(): void {
    const { containerEl } = this;
    containerEl.empty();
    containerEl.createEl("h2", { text: "Eno settings" });

    new Setting(containerEl)
      .setName("Service URL")
      .setDesc(
        "URL of the eno-service daemon. Default is local (http://127.0.0.1:7891). " +
          "For dash-main, set http://dash-main:7891 (over Tailscale)."
      )
      .addText((t) =>
        t
          .setPlaceholder("http://127.0.0.1:7891")
          .setValue(this.plugin.settings.serviceUrl)
          .onChange(async (v) => {
            this.plugin.settings.serviceUrl = v;
            await this.plugin.saveSettings();
          })
      );

    new Setting(containerEl)
      .setName("Reports folder")
      .setDesc(
        "Vault-relative folder where eno writes garden + hygiene reports. " +
          "Match this to the value the CLI uses (default: 9 Vault Health)."
      )
      .addText((t) =>
        t
          .setPlaceholder("9 Vault Health")
          .setValue(this.plugin.settings.reportsFolder)
          .onChange(async (v) => {
            this.plugin.settings.reportsFolder = v.trim() || "9 Vault Health";
            await this.plugin.saveSettings();
          })
      );
  }
}
