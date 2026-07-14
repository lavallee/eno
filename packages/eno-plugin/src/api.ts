// Thin typed client over eno-service. Uses Obsidian's requestUrl so the
// plugin works on mobile too (CORS-free, no fetch issues).

import { requestUrl } from "obsidian";
import type {
  GardenReport,
  Health,
  Neighborhood,
  NoteView,
  NoteRef,
} from "./types";

export class EnoApi {
  constructor(private getServiceUrl: () => string) {}

  private get baseUrl(): string {
    return this.getServiceUrl().replace(/\/$/, "");
  }

  private async request<T>(
    path: string,
    init?: { method?: string; body?: unknown }
  ): Promise<T> {
    const method = init?.method ?? "GET";
    const url = `${this.baseUrl}${path}`;
    const res = await requestUrl({
      url,
      method,
      contentType: "application/json",
      body: init?.body !== undefined ? JSON.stringify(init.body) : undefined,
      throw: false,
    });
    if (res.status >= 400) {
      const detail = res.text || `HTTP ${res.status}`;
      throw new Error(`${method} ${path} → ${res.status}: ${detail}`);
    }
    return res.json as T;
  }

  health(): Promise<Health> {
    return this.request<Health>("/health");
  }

  note(path: string): Promise<NoteView> {
    return this.request<NoteView>(`/note?path=${encodeURIComponent(path)}`);
  }

  neighbors(path: string): Promise<Neighborhood> {
    return this.request<Neighborhood>(
      `/neighbors?path=${encodeURIComponent(path)}`
    );
  }

  orphans(opts: { folder?: string; min_words?: number; limit?: number } = {}): Promise<NoteRef[]> {
    const params = new URLSearchParams();
    if (opts.folder) params.set("folder", opts.folder);
    if (opts.min_words !== undefined) params.set("min_words", String(opts.min_words));
    if (opts.limit !== undefined) params.set("limit", String(opts.limit));
    const qs = params.toString();
    return this.request<NoteRef[]>(`/orphans${qs ? "?" + qs : ""}`);
  }

  garden(): Promise<GardenReport> {
    return this.request<GardenReport>("/garden", { method: "POST", body: {} });
  }
}
