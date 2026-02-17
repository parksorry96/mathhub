// ─── OCR Job ────────────────────────────────────────────
export type OcrJobStatus =
  | "queued"
  | "running"
  | "partial"
  | "completed"
  | "failed";

export interface OcrJob {
  id: string;
  status: OcrJobStatus;
  fileName: string;
  totalPages: number | null;
  processedPages: number;
  errorMessage: string | null;
  createdAt: string;
  updatedAt: string;
}

// ─── Problem ────────────────────────────────────────────
export type ProblemDifficulty = "easy" | "medium" | "hard";

export interface Problem {
  id: string;
  ocrJobId: string;
  pageNumber: number;
  questionNumber: string | null;
  content: string;
  latex: string | null;
  answer: string | null;
  difficulty: ProblemDifficulty | null;
  tags: string[];
  createdAt: string;
  updatedAt: string;
}

// ─── API Response ───────────────────────────────────────
export interface ApiResponse<T> {
  success: boolean;
  data: T;
  error?: string;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  pageSize: number;
  totalPages: number;
}
