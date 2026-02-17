import { OcrJobStatus, ProblemDifficulty } from "@mathhub/shared";

// ─── Mock OCR Jobs ──────────────────────────────────────
export interface MockOcrJob {
  id: string;
  status: OcrJobStatus;
  fileName: string;
  totalPages: number | null;
  processedPages: number;
  createdAt: string;
  duration: string | null;
}

export const mockJobs: MockOcrJob[] = [
  {
    id: "job-001",
    status: "completed",
    fileName: "중3_1학기_중간고사.pdf",
    totalPages: 12,
    processedPages: 12,
    createdAt: "2026-02-17 14:30",
    duration: "2분 34초",
  },
  {
    id: "job-002",
    status: "running",
    fileName: "고1_수학(상)_단원평가.pdf",
    totalPages: 8,
    processedPages: 5,
    createdAt: "2026-02-17 15:12",
    duration: null,
  },
  {
    id: "job-003",
    status: "completed",
    fileName: "중2_2학기_기말고사.pdf",
    totalPages: 16,
    processedPages: 16,
    createdAt: "2026-02-16 09:45",
    duration: "4분 12초",
  },
  {
    id: "job-004",
    status: "failed",
    fileName: "스캔_손상파일.pdf",
    totalPages: null,
    processedPages: 0,
    createdAt: "2026-02-16 10:00",
    duration: null,
  },
  {
    id: "job-005",
    status: "queued",
    fileName: "고2_미적분_모의고사.pdf",
    totalPages: null,
    processedPages: 0,
    createdAt: "2026-02-17 15:30",
    duration: null,
  },
];

// ─── Mock Problems ──────────────────────────────────────
export interface MockProblem {
  id: string;
  questionNumber: string;
  content: string;
  difficulty: ProblemDifficulty;
  tags: string[];
  source: string;
  status: "confirmed" | "pending" | "rejected";
}

export const mockProblems: MockProblem[] = [
  {
    id: "prob-001",
    questionNumber: "1",
    content: "다항식 (2x+3)(x-1)을 전개하시오.",
    difficulty: "easy",
    tags: ["다항식", "전개"],
    source: "중3_1학기_중간고사.pdf",
    status: "confirmed",
  },
  {
    id: "prob-002",
    questionNumber: "2",
    content: "이차방정식 x²-5x+6=0의 두 근의 합을 구하시오.",
    difficulty: "medium",
    tags: ["이차방정식", "근과 계수의 관계"],
    source: "중3_1학기_중간고사.pdf",
    status: "confirmed",
  },
  {
    id: "prob-003",
    questionNumber: "3",
    content: "함수 f(x)=2x²-4x+1의 최솟값을 구하시오.",
    difficulty: "medium",
    tags: ["이차함수", "최솟값"],
    source: "중3_1학기_중간고사.pdf",
    status: "pending",
  },
  {
    id: "prob-004",
    questionNumber: "5",
    content: "sin²θ + cos²θ = 1임을 이용하여 sin30°+ cos60°의 값을 구하시오.",
    difficulty: "hard",
    tags: ["삼각함수", "항등식"],
    source: "고1_수학(상)_단원평가.pdf",
    status: "pending",
  },
  {
    id: "prob-005",
    questionNumber: "7",
    content: "등차수열 {aₙ}에서 a₃=7, a₇=19일 때, a₁₀의 값을 구하시오.",
    difficulty: "medium",
    tags: ["등차수열"],
    source: "고1_수학(상)_단원평가.pdf",
    status: "confirmed",
  },
  {
    id: "prob-006",
    questionNumber: "12",
    content: "lim(x→2) (x²-4)/(x-2)의 값을 구하시오.",
    difficulty: "easy",
    tags: ["극한"],
    source: "고2_미적분_모의고사.pdf",
    status: "pending",
  },
];

// ─── Dashboard Stats ────────────────────────────────────
export const mockStats = {
  totalProblems: 1247,
  activeJobs: 3,
  pendingReview: 28,
  successRate: 97.2,
};
