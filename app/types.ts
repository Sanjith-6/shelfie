export type RawRead = { title: string | null; author: string | null };

export type Candidate = {
  catalog_id: number;
  title: string;
  author: string;
  score: number;
  reasons: string[];
};

export type SpineStatus = "auto" | "review" | "unmatched" | "failed";

export type Spine = {
  spine_id: string;
  bbox: [number, number, number, number];
  crop_url: string;
  raw_read: RawRead;
  status: SpineStatus;
  candidates: Candidate[];
  error: string | null;
};

export type ScanResponse = {
  scan_id: string;
  timings_ms: { detect: number; vlm: number; match: number; total: number };
  detected_count: number;
  spines: Spine[];
  warnings: string[];
};

// "auto" and "confirmed" both mean the candidate as-scored was accepted -
// the difference is only whether a human looked at it first.
export type LibraryResolution = "auto" | "confirmed" | "corrected" | "manual";

export type LibraryEntry = {
  id: number;
  catalog_book: number | null;
  title: string;
  author: string;
  raw_title: string;
  raw_author: string;
  confidence: number | null;
  resolution: LibraryResolution;
  created_at: string;
};
