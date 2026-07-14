// Mirror of eno/views.py for the TS plugin. Keep in sync — when the
// Python views grow a field, add it here.

export type Health = { ok: boolean; mode?: string; vault?: string; service_url?: string };

export type NoteRef = {
  path: string;
  title: string;
  word_count: number;
  excerpt?: string | null;
};

export type Heading = { level: number; text: string; line_no: number };

export type NoteView = {
  path: string;
  title: string;
  word_count: number;
  frontmatter: Record<string, unknown>;
  headings: Heading[];
  excerpt?: string | null;
};

export type Neighborhood = {
  path: string;
  title: string;
  backlinks: NoteRef[];
  outbound: NoteRef[];
};

export type ConceptCandidate = {
  target_text: string;
  mention_count: number;
  sources: { src_path: string; line_no: number }[];
};

export type DriftCandidate = {
  target_text: string;
  suggested_path: string;
  suggested_title: string;
  score: number;
  sources: { src_path: string; line_no: number }[];
};

export type DuplicatePair = {
  path_a: string;
  path_b: string;
  title_a: string;
  title_b: string;
  score: number;
};

export type GardenReport = {
  generated_at: string;
  resurfacing: NoteRef[];
  concepts: ConceptCandidate[];
  drift: DriftCandidate[];
  stubs: NoteRef[];
  stale: NoteRef[];
  duplicates: DuplicatePair[];
  stats: Record<string, unknown>;
};

export type GardenCounts = {
  resurfacing: number;
  concepts: number;
  drift: number;
  duplicates: number;
  stubs: number;
  stale: number;
};
