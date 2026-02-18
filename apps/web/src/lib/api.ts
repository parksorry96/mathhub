const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/+$/, "") ??
  "http://localhost:8000";

export type ApiJobStatus =
  | "queued"
  | "uploading"
  | "processing"
  | "completed"
  | "failed"
  | "cancelled";

export interface OcrJobListItem {
  id: string;
  document_id: string;
  provider: string;
  provider_job_id: string | null;
  status: ApiJobStatus;
  progress_pct: string;
  error_message: string | null;
  requested_at: string;
  started_at: string | null;
  finished_at: string | null;
  storage_key: string;
  original_filename: string;
  total_pages: number;
  processed_pages: number;
  ai_done: boolean | null;
  ai_total_candidates: number | null;
  ai_candidates_processed: number | null;
  ai_candidates_accepted: number | null;
  ai_provider: string | null;
  ai_model: string | null;
}

export interface OcrJobListResponse {
  items: OcrJobListItem[];
  total: number;
  limit: number;
  offset: number;
  status_counts: Record<ApiJobStatus, number>;
}

export interface OcrPagePreviewItem {
  id: string;
  page_no: number;
  status: string;
  extracted_text: string | null;
  extracted_latex: string | null;
  updated_at: string;
}

export interface OcrJobPagesResponse {
  job_id: string;
  items: OcrPagePreviewItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface OcrQuestionAssetPreview {
  asset_type: string;
  storage_key: string;
  preview_url: string | null;
  page_no: number | null;
  bbox: Record<string, number> | null;
}

export interface OcrQuestionPreviewItem {
  page_id: string;
  page_no: number;
  candidate_no: number;
  candidate_index: number;
  candidate_key: string;
  external_problem_key: string;
  split_strategy: string;
  statement_text: string;
  confidence: string | null;
  validation_status: string | null;
  provider: string | null;
  model: string | null;
  has_visual_asset: boolean;
  asset_types: string[];
  asset_previews: OcrQuestionAssetPreview[];
  updated_at: string;
}

export interface OcrJobQuestionsResponse {
  job_id: string;
  items: OcrQuestionPreviewItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface OcrJobAiClassifyStepResponse {
  job_id: string;
  done: boolean;
  processed_in_call: number;
  total_candidates: number;
  candidates_processed: number;
  candidates_accepted: number;
  provider: string;
  model: string;
  current_page_no: number | null;
  current_candidate_no: number | null;
  current_candidate_provider: string | null;
}

export interface OcrJobMathpixSubmitResponse {
  job_id: string;
  provider_job_id: string;
  status: string;
  progress_pct: string;
  requested_at: string;
  started_at: string | null;
}

export interface OcrJobMathpixSyncResponse {
  job_id: string;
  provider_job_id: string;
  status: ApiJobStatus;
  progress_pct: string;
  pages_upserted: number;
  error_message: string | null;
}

export interface OcrJobMaterializeResponse {
  job_id: string;
  curriculum_code: string;
  source_id: string | null;
  inserted_count: number;
  updated_count: number;
  skipped_count: number;
  results: Array<{
    page_no: number;
    candidate_no: number;
    status: string;
    problem_id: string | null;
    external_problem_key: string;
    reason: string | null;
  }>;
}

export interface ProblemAssetItem {
  id: string;
  asset_type: string;
  storage_key: string;
  preview_url: string | null;
  page_no: number | null;
  bbox: Record<string, number> | null;
}

export interface ProblemListItem {
  id: string;
  ocr_page_id: string | null;
  ocr_job_id: string | null;
  external_problem_key: string | null;
  source_problem_no: number | null;
  source_problem_label: string | null;
  content: string | null;
  point_value: number;
  subject_code: string | null;
  subject_name_ko: string | null;
  unit_code: string | null;
  unit_name_ko: string | null;
  source_title: string | null;
  source_category: string | null;
  source_type: string | null;
  document_filename: string | null;
  review_status: "pending" | "approved" | "rejected";
  confidence: string | null;
  ai_reviewed: boolean;
  ai_provider: string | null;
  ai_model: string | null;
  assets: ProblemAssetItem[];
  is_verified: boolean;
  created_at: string;
  updated_at: string;
}

export interface ProblemListResponse {
  items: ProblemListItem[];
  total: number;
  limit: number;
  offset: number;
  review_counts: Record<"pending" | "approved" | "rejected", number>;
}

export interface ProblemReviewResponse {
  id: string;
  review_status: "approved" | "rejected";
  is_verified: boolean;
  verified_at: string | null;
  updated_at: string;
}

export interface CreateOcrJobPayload {
  storage_key: string;
  original_filename: string;
  mime_type: string;
  file_size_bytes: number;
  sha256: string;
  provider?: string;
}

export interface CreateOcrJobResponse {
  id: string;
  document_id: string;
  provider: string;
  status: string;
  progress_pct: string;
  requested_at: string;
}

export interface DeleteOcrJobResponse {
  job_id: string;
  document_id: string;
  source_deleted: boolean;
}

export interface S3PresignUploadRequest {
  filename: string;
  content_type: string;
  prefix?: string;
  expires_in_sec?: number;
}

export interface S3PresignUploadResponse {
  bucket: string;
  key: string;
  storage_key: string;
  upload_url: string;
  download_url: string;
  upload_method: "PUT";
  upload_headers: Record<string, string>;
  expires_in_sec: number;
}

interface RequestInitEx extends RequestInit {
  query?: Record<string, string | number | boolean | undefined | null>;
}

function buildUrl(path: string, query?: RequestInitEx["query"]) {
  const url = new URL(`${API_BASE_URL}${path}`);
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value === undefined || value === null || value === "") continue;
      url.searchParams.set(key, String(value));
    }
  }
  return url.toString();
}

async function requestJson<T>(path: string, init: RequestInitEx = {}): Promise<T> {
  const { query, ...rest } = init;
  const response = await fetch(buildUrl(path, query), {
    ...rest,
    headers: {
      "Content-Type": "application/json",
      ...(rest.headers ?? {}),
    },
    cache: "no-store",
  });

  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const err = (await response.json()) as { detail?: string };
      if (err.detail) {
        message = err.detail;
      }
    } catch {
      // keep fallback message
    }
    throw new Error(message);
  }

  return (await response.json()) as T;
}

export function listOcrJobs(params?: {
  limit?: number;
  offset?: number;
  status?: string;
  q?: string;
}) {
  return requestJson<OcrJobListResponse>("/ocr/jobs", {
    method: "GET",
    query: params,
  });
}

export function listOcrJobPages(jobId: string, params?: { limit?: number; offset?: number }) {
  return requestJson<OcrJobPagesResponse>(`/ocr/jobs/${jobId}/pages`, {
    method: "GET",
    query: params,
  });
}

export function listOcrJobQuestions(jobId: string, params?: { limit?: number; offset?: number }) {
  return requestJson<OcrJobQuestionsResponse>(`/ocr/jobs/${jobId}/questions`, {
    method: "GET",
    query: params,
  });
}

export function createOcrJob(payload: CreateOcrJobPayload) {
  return requestJson<CreateOcrJobResponse>("/ocr/jobs", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function deleteOcrJob(jobId: string, opts?: { delete_source?: boolean }) {
  return requestJson<DeleteOcrJobResponse>(`/ocr/jobs/${jobId}`, {
    method: "DELETE",
    query: { delete_source: opts?.delete_source ?? true },
  });
}

export function presignS3Upload(payload: S3PresignUploadRequest) {
  return requestJson<S3PresignUploadResponse>("/storage/s3/presign-upload", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function uploadFileToS3PresignedUrl(params: {
  uploadUrl: string;
  file: File;
  headers?: Record<string, string>;
}) {
  const response = await fetch(params.uploadUrl, {
    method: "PUT",
    body: params.file,
    headers: params.headers ?? {},
  });
  if (!response.ok) {
    throw new Error(`S3 upload failed: ${response.status} ${response.statusText}`);
  }
}

export function submitMathpixJob(jobId: string, payload?: Record<string, unknown>) {
  return requestJson<OcrJobMathpixSubmitResponse>(`/ocr/jobs/${jobId}/mathpix/submit`, {
    method: "POST",
    body: JSON.stringify(payload ?? {}),
  });
}

export function syncMathpixJob(jobId: string, payload?: Record<string, unknown>) {
  return requestJson<OcrJobMathpixSyncResponse>(`/ocr/jobs/${jobId}/mathpix/sync`, {
    method: "POST",
    body: JSON.stringify(payload ?? {}),
  });
}

export function classifyOcrJob(jobId: string, payload?: Record<string, unknown>) {
  return requestJson(`/ocr/jobs/${jobId}/ai-classify`, {
    method: "POST",
    body: JSON.stringify(payload ?? {}),
  });
}

export function classifyOcrJobStep(jobId: string, payload?: Record<string, unknown>) {
  return requestJson<OcrJobAiClassifyStepResponse>(`/ocr/jobs/${jobId}/ai-classify/step`, {
    method: "POST",
    body: JSON.stringify(payload ?? {}),
  });
}

export function materializeProblems(jobId: string, payload?: Record<string, unknown>) {
  return requestJson<OcrJobMaterializeResponse>(`/ocr/jobs/${jobId}/materialize-problems`, {
    method: "POST",
    body: JSON.stringify(payload ?? {}),
  });
}

export function listProblems(params?: {
  limit?: number;
  offset?: number;
  q?: string;
  review_status?: "pending" | "approved" | "rejected";
  ai_reviewed?: boolean;
}) {
  return requestJson<ProblemListResponse>("/problems", {
    method: "GET",
    query: params,
  });
}

export function reviewProblem(
  problemId: string,
  payload: { action: "approve" | "reject"; note?: string },
) {
  return requestJson<ProblemReviewResponse>(`/problems/${problemId}/review`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}
