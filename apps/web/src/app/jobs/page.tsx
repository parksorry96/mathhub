"use client";

import { type MouseEvent, useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  InputAdornment,
  LinearProgress,
  Menu,
  MenuItem,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Tooltip,
  Typography,
  useMediaQuery,
} from "@mui/material";
import { useTheme } from "@mui/material/styles";
import SearchRoundedIcon from "@mui/icons-material/SearchRounded";
import RefreshRoundedIcon from "@mui/icons-material/RefreshRounded";
import AutoAwesomeRoundedIcon from "@mui/icons-material/AutoAwesomeRounded";
import VisibilityRoundedIcon from "@mui/icons-material/VisibilityRounded";
import MoreHorizRoundedIcon from "@mui/icons-material/MoreHorizRounded";
import { MathJaxContext } from "better-react-mathjax";
import { ProblemStatementView } from "@/components/problem-statement-view";
import type {
  ApiJobStatus,
  OcrJobAiClassifyStepResponse,
  OcrJobListItem,
  OcrJobMathpixSyncResponse,
  OcrPagePreviewItem,
  OcrQuestionPreviewItem,
} from "@/lib/api";
import {
  classifyOcrJobStep,
  deleteOcrJob,
  listOcrJobPages,
  listOcrJobQuestions,
  listOcrJobs,
  materializeProblems,
  preprocessOcrJobWithAi,
  runProblemOcrPipeline,
  submitMathpixJob,
  syncMathpixJob,
} from "@/lib/api";

type FilterStatus = ApiJobStatus | "all";

const statusConfig: Record<ApiJobStatus, { label: string; color: string; bg: string }> = {
  completed: { label: "완료", color: "#778C86", bg: "rgba(119,140,134,0.12)" },
  processing: { label: "진행중", color: "#E7E3E3", bg: "rgba(231,227,227,0.08)" },
  uploading: { label: "업로드", color: "#E7E3E3", bg: "rgba(231,227,227,0.08)" },
  queued: { label: "대기", color: "#919497", bg: "rgba(145,148,151,0.1)" },
  failed: { label: "실패", color: "#C45C5C", bg: "rgba(196,92,92,0.12)" },
  cancelled: { label: "취소", color: "#C45C5C", bg: "rgba(196,92,92,0.12)" },
};

const mathJaxConfig = {
  tex: {
    inlineMath: [["\\(", "\\)"]],
    displayMath: [["\\[", "\\]"]],
  },
};

const QUESTION_SPLIT_PATTERNS: Array<{ strategy: string; pattern: RegExp }> = [
  { strategy: "numbered", pattern: /^\s*(\d{1,2})\s*[\.)]\s+/gm },
  { strategy: "bracketed", pattern: /^\s*\[(\d{1,2})\]\s+/gm },
  { strategy: "question_label", pattern: /^\s*문항\s*(\d{1,2})\s*(?:번)?\s*[:.)]?\s*/gm },
  { strategy: "number_with_beon", pattern: /^\s*(\d{1,2})\s*번\s+/gm },
];

const VISUAL_HINT_PATTERNS: Array<{ assetType: string; pattern: RegExp }> = [
  { assetType: "graph", pattern: /(그래프|좌표평면|plot|graph|chart|곡선)/i },
  { assetType: "table", pattern: /(도수분포표|표|table|tabular)/i },
  { assetType: "image", pattern: /(그림|도형|diagram|figure|image|사진)/i },
];

function formatDate(dateText: string) {
  return new Date(dateText).toLocaleString("ko-KR", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatDuration(startedAt: string | null, finishedAt: string | null) {
  if (!startedAt || !finishedAt) return "—";
  const diffMs = new Date(finishedAt).getTime() - new Date(startedAt).getTime();
  if (!Number.isFinite(diffMs) || diffMs <= 0) return "—";
  const totalSec = Math.floor(diffMs / 1000);
  const min = Math.floor(totalSec / 60);
  const sec = totalSec % 60;
  return `${min}분 ${sec}초`;
}

function toNumber(text: string) {
  const value = Number(text);
  return Number.isFinite(value) ? value : 0;
}

function isMathpixSubmitSourceSupported(storageKey: string) {
  const key = storageKey.trim();
  return key.startsWith("s3://") || key.startsWith("http://") || key.startsWith("https://");
}

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function toQuestionPreviewItemsFromPages(pages: OcrPagePreviewItem[]): OcrQuestionPreviewItem[] {
  const items: OcrQuestionPreviewItem[] = [];
  for (const page of pages) {
    const pageText = (page.extracted_text || page.extracted_latex || "").trim();
    if (!pageText) {
      continue;
    }

    const candidates = splitQuestionCandidates(pageText);
    for (const candidate of candidates) {
      const assetTypes = detectVisualAssetTypes(candidate.statement_text);
      items.push({
        page_id: page.id,
        page_no: page.page_no,
        candidate_no: candidate.candidate_no,
        candidate_index: candidate.candidate_index,
        candidate_key: `P${page.page_no}-C${candidate.candidate_no}`,
        external_problem_key: `OCR:FALLBACK:P${page.page_no}:I${candidate.candidate_index}`,
        split_strategy: candidate.split_strategy,
        statement_text: candidate.statement_text,
        confidence: null,
        validation_status: null,
        provider: null,
        model: null,
        has_visual_asset: assetTypes.length > 0,
        asset_types: assetTypes,
        asset_previews: [],
        updated_at: page.updated_at,
      });
    }
  }
  return items.sort((a, b) => a.page_no - b.page_no || a.candidate_no - b.candidate_no);
}

function splitQuestionCandidates(
  text: string,
): Array<{ candidate_no: number; candidate_index: number; statement_text: string; split_strategy: string }> {
  const cleaned = text.trim();
  if (!cleaned) return [];

  let bestStrategy = "full_page_fallback";
  let bestMatches: Array<{ index: number; value: number }> = [];
  let bestScore = -1;

  for (const entry of QUESTION_SPLIT_PATTERNS) {
    const matches = Array.from(cleaned.matchAll(entry.pattern))
      .map((m) => {
        const idx = m.index;
        const raw = m[1];
        const parsed = Number(raw);
        if (idx === undefined || !Number.isFinite(parsed)) return null;
        return { index: idx, value: parsed };
      })
      .filter((m): m is { index: number; value: number } => m !== null);
    if (matches.length === 0) continue;

    const sequenceBonus = isLikelyQuestionSequence(matches.map((m) => m.value)) ? 2 : 0;
    const score = matches.length + sequenceBonus;
    if (score > bestScore) {
      bestScore = score;
      bestMatches = matches;
      bestStrategy = entry.strategy;
    }
  }

  if (bestMatches.length === 0) {
    return [{ candidate_no: 1, candidate_index: 1, statement_text: cleaned, split_strategy: "full_page_fallback" }];
  }

  const candidates: Array<{ candidate_no: number; candidate_index: number; statement_text: string; split_strategy: string }> = [];
  for (let i = 0; i < bestMatches.length; i += 1) {
    const start = bestMatches[i].index;
    const end = i + 1 < bestMatches.length ? bestMatches[i + 1].index : cleaned.length;
    const statementText = cleaned.slice(start, end).trim();
    if (!statementText) continue;
    candidates.push({
      candidate_no: bestMatches[i].value,
      candidate_index: i + 1,
      statement_text: statementText,
      split_strategy: bestStrategy,
    });
  }
  return candidates.length > 0
    ? candidates
    : [{ candidate_no: 1, candidate_index: 1, statement_text: cleaned, split_strategy: "full_page_fallback" }];
}

function isLikelyQuestionSequence(numbers: number[]) {
  if (numbers.length <= 1) return false;
  let increasing = 0;
  for (let i = 1; i < numbers.length; i += 1) {
    const diff = numbers[i] - numbers[i - 1];
    if (diff > 0 && diff <= 3) increasing += 1;
  }
  return increasing >= Math.max(1, numbers.length - 2);
}

function detectVisualAssetTypes(statementText: string): string[] {
  const detected = new Set<string>();
  for (const hint of VISUAL_HINT_PATTERNS) {
    if (hint.pattern.test(statementText)) {
      detected.add(hint.assetType);
    }
  }
  return Array.from(detected).sort();
}

export default function JobsPage() {
  const theme = useTheme();
  const isMobilePreview = useMediaQuery(theme.breakpoints.down("md"));
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [jobs, setJobs] = useState<OcrJobListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [searchText, setSearchText] = useState("");
  const [statusFilter, setStatusFilter] = useState<FilterStatus>("all");
  const [runningAction, setRunningAction] = useState<Record<string, string>>({});
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewTitle, setPreviewTitle] = useState("");
  const [previewQuestions, setPreviewQuestions] = useState<OcrQuestionPreviewItem[]>([]);
  const [previewSelectedIndex, setPreviewSelectedIndex] = useState(0);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [actionMenuAnchorEl, setActionMenuAnchorEl] = useState<HTMLElement | null>(null);
  const [actionMenuJobId, setActionMenuJobId] = useState<string | null>(null);

  const loadJobs = useCallback(
    async (search: string, status: FilterStatus, options?: { silent?: boolean }) => {
      const silent = options?.silent ?? false;
      if (!silent) {
        setLoading(true);
        setError(null);
      }
      try {
        const res = await listOcrJobs({
          limit: 100,
          offset: 0,
          q: search || undefined,
          status: status === "all" ? undefined : status,
        });
        setJobs(res.items);
        setTotal(res.total);
      } catch (err) {
        if (!silent) {
          setError(err instanceof Error ? err.message : "작업 목록을 불러오지 못했습니다.");
        }
      } finally {
        if (!silent) {
          setLoading(false);
        }
      }
    },
    [],
  );

  const patchJob = useCallback((jobId: string, patch: Partial<OcrJobListItem>) => {
    setJobs((prev) => prev.map((item) => (item.id === jobId ? { ...item, ...patch } : item)));
  }, []);
  const closeActionMenu = useCallback(() => {
    setActionMenuAnchorEl(null);
    setActionMenuJobId(null);
  }, []);
  const openActionMenu = useCallback((event: MouseEvent<HTMLElement>, job: OcrJobListItem) => {
    setActionMenuAnchorEl(event.currentTarget);
    setActionMenuJobId(job.id);
  }, []);

  useEffect(() => {
    const timer = setTimeout(() => {
      void loadJobs(searchText.trim(), statusFilter);
    }, 250);
    return () => clearTimeout(timer);
  }, [searchText, statusFilter, loadJobs]);

  const hasPendingServerUpdates = useMemo(() => {
    if (Object.keys(runningAction).length > 0) {
      return true;
    }
    return jobs.some((item) => item.status === "queued" || item.status === "uploading" || item.status === "processing");
  }, [jobs, runningAction]);

  useEffect(() => {
    if (!hasPendingServerUpdates) {
      return;
    }
    const timer = setInterval(() => {
      void loadJobs(searchText.trim(), statusFilter, { silent: true });
    }, 2500);
    return () => clearInterval(timer);
  }, [hasPendingServerUpdates, loadJobs, searchText, statusFilter]);

  const runClassifyLoop = useCallback(async (job: OcrJobListItem): Promise<OcrJobAiClassifyStepResponse> => {
    let latest: OcrJobAiClassifyStepResponse | null = null;
    let attempts = 0;
    const maxAttempts = 3000;
    while (attempts < maxAttempts) {
      const step = await classifyOcrJobStep(job.id, {
        max_pages: 50,
        min_confidence: 0,
        max_candidates_per_call: 8,
      });
      latest = step;
      patchJob(job.id, {
        ai_done: step.done,
        ai_total_candidates: step.total_candidates,
        ai_candidates_processed: step.candidates_processed,
        ai_candidates_accepted: step.candidates_accepted,
        ai_provider: step.provider,
        ai_model: step.model,
      });
      if (!step.done) {
        const at =
          step.current_page_no && step.current_candidate_no
            ? ` (P${step.current_page_no}-C${step.current_candidate_no})`
            : "";
        setNotice(`${job.original_filename}: AI 분류 진행중 ${step.candidates_processed}/${step.total_candidates}${at}`);
      }
      if (step.done) break;
      attempts += 1;
    }
    if (!latest) {
      throw new Error("AI 분류 응답을 받지 못했습니다.");
    }
    if (!latest.done) {
      throw new Error("AI 분류가 시간 내 완료되지 않았습니다. 다시 시도해주세요.");
    }
    return latest;
  }, [patchJob]);

  const runSyncUntilCompleted = useCallback(async (job: OcrJobListItem): Promise<OcrJobMathpixSyncResponse> => {
    const terminalStatuses: ApiJobStatus[] = ["completed", "failed", "cancelled"];
    const maxAttempts = 180;
    let attempts = 0;
    let latest: OcrJobMathpixSyncResponse | null = null;

    while (attempts < maxAttempts) {
      const step = await syncMathpixJob(job.id, {});
      latest = step;
      patchJob(job.id, {
        status: step.status,
        progress_pct: step.progress_pct,
        error_message: step.error_message,
      });
      setNotice(`${job.original_filename}: OCR 동기화 ${toNumber(step.progress_pct).toFixed(0)}% (${step.status})`);
      if (terminalStatuses.includes(step.status)) {
        break;
      }
      attempts += 1;
      await sleep(2000);
    }

    if (!latest) {
      throw new Error("Mathpix 동기화 응답을 받지 못했습니다.");
    }
    if (latest.status === "failed") {
      throw new Error(latest.error_message || "Mathpix 처리에 실패했습니다.");
    }
    if (latest.status === "cancelled") {
      throw new Error("Mathpix 작업이 취소되었습니다.");
    }
    if (latest.status !== "completed") {
      throw new Error("Mathpix 동기화가 시간 내 완료되지 않았습니다. 다시 시도해주세요.");
    }
    return latest;
  }, [patchJob]);

  const runAction = useCallback(
    async (
      job: OcrJobListItem,
      action: "pipeline" | "submit" | "sync" | "classify" | "materialize" | "delete",
    ) => {
      setNotice(null);
      setError(null);
      setRunningAction((prev) => ({ ...prev, [job.id]: action }));
      try {
        if (action === "pipeline") {
          setNotice(`${job.original_filename}: AI 페이지 스캔 시작`);
          const preprocessed = await preprocessOcrJobWithAi(job.id, {
            max_pages: 500,
            render_scale: 1.35,
            temperature: 0.1,
            max_parallel_pages: 3,
            max_output_tokens: 2048,
            thinking_budget: 0,
          });
          setNotice(
            `${job.original_filename}: AI 스캔 완료 (페이지 ${preprocessed.scanned_pages}, 문항 ${preprocessed.detected_problems}, 정답매칭 ${preprocessed.matched_answers})`,
          );
          const ocrResult = await runProblemOcrPipeline(job.id, {
            curriculum_code: "CSAT_2027",
            source_category: "other",
            source_type: "workbook",
            textbook_title: job.original_filename,
            min_confidence: 0,
            default_point_value: 3,
            default_response_type: "short_answer",
            default_answer_key: "PENDING_REVIEW",
          });
          setNotice(
            `${job.original_filename}: 자동실행 완료 (문항OCR ${ocrResult.processed_candidates}, 적재 +${ocrResult.inserted_count}/${ocrResult.updated_count}, 스킵 ${ocrResult.skipped_count})`,
          );
        } else if (action === "submit") {
          const submitResult = await submitMathpixJob(job.id, {});
          patchJob(job.id, {
            provider_job_id: submitResult.provider_job_id,
            status: submitResult.status as ApiJobStatus,
            progress_pct: submitResult.progress_pct,
            started_at: submitResult.started_at ?? job.started_at,
          });
          setNotice(`${job.original_filename}: Mathpix 제출 완료, 자동 동기화 시작`);
          const syncResult = await runSyncUntilCompleted(job);
          setNotice(`${job.original_filename}: OCR 동기화 완료 (${toNumber(syncResult.progress_pct).toFixed(0)}%)`);
        } else if (action === "sync") {
          const syncResult = await runSyncUntilCompleted(job);
          setNotice(
            `${job.original_filename}: Mathpix 동기화 완료 (${syncResult.status}, ${toNumber(syncResult.progress_pct).toFixed(0)}%)`,
          );
        } else if (action === "classify") {
          setNotice(`${job.original_filename}: AI 분류 시작`);
          const latest = await runClassifyLoop(job);
          setNotice(
            `${job.original_filename}: AI 분류 완료 (${latest.provider}, ${latest.candidates_processed}/${latest.total_candidates})`,
          );
        } else if (action === "materialize") {
          await materializeProblems(job.id, {
            curriculum_code: "CSAT_2027",
            min_confidence: 0,
            default_point_value: 3,
            default_response_type: "short_answer",
            default_answer_key: "PENDING_REVIEW",
          });
          setNotice(`${job.original_filename}: 문제은행 적재 완료`);
        } else {
          const deleted = await deleteOcrJob(job.id, { delete_source: true });
          setNotice(
            deleted.source_deleted
              ? `${job.original_filename}: 작업/원본 삭제 완료`
              : `${job.original_filename}: 작업 삭제 완료 (원본 삭제는 건너뛰었거나 실패)`,
          );
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "작업 실행에 실패했습니다.");
      } finally {
        setRunningAction((prev) => {
          const next = { ...prev };
          delete next[job.id];
          return next;
        });
        await loadJobs(searchText.trim(), statusFilter, { silent: true });
      }
    },
    [loadJobs, patchJob, runClassifyLoop, runSyncUntilCompleted, searchText, statusFilter],
  );

  const actionMenuJob = useMemo(() => jobs.find((item) => item.id === actionMenuJobId) ?? null, [jobs, actionMenuJobId]);
  const actionMenuBusy = actionMenuJob ? runningAction[actionMenuJob.id] : undefined;
  const actionMenuSubmitSourceSupported = actionMenuJob ? isMathpixSubmitSourceSupported(actionMenuJob.storage_key) : false;
  const actionMenuSubmitDisabled =
    !actionMenuJob || Boolean(actionMenuBusy) || !!actionMenuJob.provider_job_id || !actionMenuSubmitSourceSupported;
  const actionMenuSyncDisabled = !actionMenuJob || Boolean(actionMenuBusy) || !actionMenuJob.provider_job_id;
  const actionMenuClassifyDisabled = !actionMenuJob || Boolean(actionMenuBusy);
  const actionMenuMaterializeDisabled = !actionMenuJob || Boolean(actionMenuBusy);
  const actionMenuDeleteDisabled = !actionMenuJob || Boolean(actionMenuBusy);

  const runActionFromMenu = useCallback(
    (action: "submit" | "sync" | "classify" | "materialize" | "delete") => {
      if (!actionMenuJob) return;
      const targetJob = actionMenuJob;
      closeActionMenu();
      if (action === "delete") {
        const ok = window.confirm("이 작업을 삭제할까요?\n(참조가 없으면 원본 S3 파일도 함께 삭제 시도됩니다.)");
        if (!ok) return;
      }
      void runAction(targetJob, action);
    },
    [actionMenuJob, closeActionMenu, runAction],
  );

  const openPreview = useCallback(async (job: OcrJobListItem) => {
    setPreviewOpen(true);
    setPreviewTitle(job.original_filename);
    setPreviewQuestions([]);
    setPreviewSelectedIndex(0);
    setPreviewError(null);
    setPreviewLoading(true);
    try {
      try {
        const res = await listOcrJobQuestions(job.id, { limit: 1000, offset: 0 });
        setPreviewQuestions(res.items);
        if (res.items.length === 0) {
          setPreviewError("문항 단위 미리보기가 없습니다. OCR 동기화를 먼저 실행하세요.");
        }
      } catch (err) {
        const message = err instanceof Error ? err.message : "";
        const isQuestionsApiUnavailable =
          message.includes("404") || message.toLowerCase().includes("not found");
        if (!isQuestionsApiUnavailable) {
          throw err;
        }
        const pageRes = await listOcrJobPages(job.id, { limit: 50, offset: 0 });
        const fallbackItems = toQuestionPreviewItemsFromPages(pageRes.items);
        setPreviewQuestions(fallbackItems);
        if (fallbackItems.length === 0) {
          setPreviewError("문항 단위 미리보기가 없습니다. OCR 동기화를 먼저 실행하세요.");
        } else {
          setNotice(`${job.original_filename}: 구버전 API 감지, 페이지 기반 문항 분할로 미리보기를 표시했습니다.`);
        }
      }
    } catch (err) {
      setPreviewError(err instanceof Error ? err.message : "문항 미리보기를 불러오지 못했습니다.");
    } finally {
      setPreviewLoading(false);
    }
  }, []);

  const visibleStatuses = useMemo(
    () => ["completed", "processing", "uploading", "queued", "failed", "cancelled"] as ApiJobStatus[],
    [],
  );
  const selectedPreviewQuestion = previewQuestions[previewSelectedIndex] ?? null;

  useEffect(() => {
    if (previewQuestions.length === 0) {
      setPreviewSelectedIndex(0);
      return;
    }
    if (previewSelectedIndex >= previewQuestions.length) {
      setPreviewSelectedIndex(previewQuestions.length - 1);
    }
  }, [previewQuestions, previewSelectedIndex]);

  return (
    <Box>
      <Box sx={{ mb: 4 }}>
        <Typography variant="h4" sx={{ fontWeight: 700, color: "#FFFFFF" }}>
          작업 목록
        </Typography>
        <Typography variant="body2" sx={{ color: "#919497", mt: 0.5 }}>
          실제 API 연동 상태 관리 (자동실행/제출/동기화/AI 분류/문제 적재)
        </Typography>
      </Box>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}
      {notice && (
        <Alert severity="success" sx={{ mb: 2 }}>
          {notice}
        </Alert>
      )}

      <Box sx={{ mb: 3, display: "flex", gap: 1.5, alignItems: "center", flexWrap: "wrap" }}>
        <TextField
          size="small"
          placeholder="파일명/스토리지키 검색..."
          value={searchText}
          onChange={(e) => setSearchText(e.target.value)}
          slotProps={{
            input: {
              startAdornment: (
                <InputAdornment position="start">
                  <SearchRoundedIcon sx={{ fontSize: 18, color: "#919497" }} />
                </InputAdornment>
              ),
            },
          }}
          sx={{
            width: 320,
            "& .MuiOutlinedInput-root": {
              backgroundColor: "#141414",
              fontSize: 13,
              "& fieldset": { borderColor: "rgba(231,227,227,0.08)" },
              "&:hover fieldset": { borderColor: "rgba(231,227,227,0.15)" },
              "&.Mui-focused fieldset": { borderColor: "#E7E3E3" },
            },
            "& input": { color: "#FFFFFF" },
          }}
        />
        <Chip
          label="전체"
          size="small"
          onClick={() => setStatusFilter("all")}
          variant={statusFilter === "all" ? "filled" : "outlined"}
          sx={{
            borderColor: "rgba(231,227,227,0.12)",
            color: statusFilter === "all" ? "#FFFFFF" : "#919497",
            backgroundColor: statusFilter === "all" ? "rgba(255,255,255,0.08)" : "transparent",
            fontSize: 12,
          }}
        />
        {visibleStatuses.map((s) => (
          <Chip
            key={s}
            label={statusConfig[s].label}
            size="small"
            onClick={() => setStatusFilter(s)}
            variant={statusFilter === s ? "filled" : "outlined"}
            sx={{
              borderColor: "rgba(231,227,227,0.12)",
              color: statusFilter === s ? statusConfig[s].color : "#919497",
              backgroundColor: statusFilter === s ? statusConfig[s].bg : "transparent",
              fontSize: 12,
            }}
          />
        ))}
        <IconButton size="small" sx={{ color: "#919497" }} onClick={() => void loadJobs(searchText.trim(), statusFilter)}>
          <RefreshRoundedIcon fontSize="small" />
        </IconButton>
        <Typography variant="caption" sx={{ color: "#919497" }}>
          총 {total.toLocaleString()}건
        </Typography>
      </Box>

      <Card>
        <CardContent sx={{ p: 0 }}>
          <TableContainer>
            <Table>
              <TableHead>
                <TableRow>
                  <TableCell>파일명</TableCell>
                  <TableCell>상태</TableCell>
                  <TableCell>진행률</TableCell>
                  <TableCell>소요시간</TableCell>
                  <TableCell>생성일시</TableCell>
                  <TableCell align="right">작업</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {jobs.map((job) => {
                  const status = statusConfig[job.status];
                  const busy = runningAction[job.id];
                  const submitSourceSupported = isMathpixSubmitSourceSupported(job.storage_key);
                  const pipelineDisabled = Boolean(busy) || !submitSourceSupported;
                  const aiTotal = job.ai_total_candidates ?? 0;
                  const aiProcessed = job.ai_candidates_processed ?? 0;
                  const aiAccepted = job.ai_candidates_accepted ?? 0;
                  const hasAiProgress =
                    job.ai_done !== null ||
                    job.ai_total_candidates !== null ||
                    job.ai_candidates_processed !== null;
                  const pipelineTooltip = busy
                    ? "실행 중"
                    : !submitSourceSupported
                      ? "legacy storage_key(upload://)는 자동실행을 시작할 수 없습니다. 새로 업로드 후 시도하세요."
                      : "전체 자동 실행 (AI 스캔→문항 분할/정답매칭→문제별 OCR→문제 적재)";
                  return (
                    <TableRow key={job.id} sx={{ "&:hover": { backgroundColor: "rgba(255,255,255,0.02)" } }}>
                      <TableCell>
                        <Typography variant="body2" sx={{ color: "#FFFFFF", fontWeight: 500, fontSize: 13 }}>
                          {job.original_filename}
                        </Typography>
                        <Typography variant="caption" sx={{ color: "#52525B" }}>
                          {job.id}
                        </Typography>
                      </TableCell>
                      <TableCell>
                        <Chip
                          label={status.label}
                          size="small"
                          sx={{
                            color: status.color,
                            backgroundColor: status.bg,
                            fontWeight: 500,
                            fontSize: 11,
                            height: 22,
                          }}
                        />
                      </TableCell>
                      <TableCell sx={{ minWidth: 140 }}>
                        <LinearProgress
                          variant="determinate"
                          value={toNumber(job.progress_pct)}
                          sx={{
                            height: 4,
                            "& .MuiLinearProgress-bar": {
                              backgroundColor: job.status === "completed" ? "#778C86" : "#E7E3E3",
                            },
                          }}
                        />
                        <Typography variant="caption" sx={{ color: "#919497" }}>
                          {job.processed_pages}/{job.total_pages || 0} 페이지 ({toNumber(job.progress_pct).toFixed(0)}%)
                        </Typography>
                        {hasAiProgress && (
                          <Typography variant="caption" sx={{ color: "#7FB3FF", display: "block", mt: 0.25 }}>
                            AI {aiProcessed}/{aiTotal}
                            {job.ai_done ? " 완료" : " 진행중"}
                            {` · 승인 ${aiAccepted}`}
                            {job.ai_provider ? ` · ${job.ai_provider}` : ""}
                          </Typography>
                        )}
                      </TableCell>
                      <TableCell>
                        <Typography variant="body2" sx={{ color: "#919497", fontSize: 13 }}>
                          {formatDuration(job.started_at, job.finished_at)}
                        </Typography>
                      </TableCell>
                      <TableCell>
                        <Typography variant="body2" sx={{ color: "#919497", fontSize: 13 }}>
                          {formatDate(job.requested_at)}
                        </Typography>
                      </TableCell>
                      <TableCell align="right">
                        <Box sx={{ display: "flex", justifyContent: "flex-end", gap: 0.5 }}>
                          <Tooltip title={pipelineTooltip}>
                            <span>
                              <IconButton
                                size="small"
                                sx={{ color: "#D4A574" }}
                                disabled={pipelineDisabled}
                                onClick={() => void runAction(job, "pipeline")}
                              >
                                <AutoAwesomeRoundedIcon sx={{ fontSize: 16 }} />
                              </IconButton>
                            </span>
                          </Tooltip>
                          <Tooltip title={busy ? "실행 중" : "문항 미리보기"}>
                            <span>
                              <IconButton
                                size="small"
                                sx={{ color: "#919497" }}
                                disabled={Boolean(busy)}
                                onClick={() => void openPreview(job)}
                              >
                                <VisibilityRoundedIcon sx={{ fontSize: 16 }} />
                              </IconButton>
                            </span>
                          </Tooltip>
                          <Tooltip title={busy ? "실행 중" : "상세 작업"}>
                            <span>
                              <IconButton
                                size="small"
                                sx={{ color: "#919497" }}
                                disabled={Boolean(busy)}
                                onClick={(event) => openActionMenu(event, job)}
                              >
                                <MoreHorizRoundedIcon sx={{ fontSize: 16 }} />
                              </IconButton>
                            </span>
                          </Tooltip>
                        </Box>
                      </TableCell>
                    </TableRow>
                  );
                })}
                {!loading && jobs.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={6}>
                      <Typography variant="body2" sx={{ color: "#919497", py: 2 }}>
                        조건에 맞는 작업이 없습니다.
                      </Typography>
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </TableContainer>
        </CardContent>
      </Card>

      <Menu
        anchorEl={actionMenuAnchorEl}
        open={Boolean(actionMenuAnchorEl) && Boolean(actionMenuJob)}
        onClose={closeActionMenu}
      >
        <MenuItem disabled={actionMenuSubmitDisabled} onClick={() => runActionFromMenu("submit")}>
          Mathpix 제출 + 동기화
        </MenuItem>
        <MenuItem disabled={actionMenuSyncDisabled} onClick={() => runActionFromMenu("sync")}>
          Mathpix 동기화
        </MenuItem>
        <MenuItem disabled={actionMenuClassifyDisabled} onClick={() => runActionFromMenu("classify")}>
          AI 분류
        </MenuItem>
        <MenuItem disabled={actionMenuMaterializeDisabled} onClick={() => runActionFromMenu("materialize")}>
          문제 적재
        </MenuItem>
        <MenuItem
          disabled={actionMenuDeleteDisabled}
          onClick={() => runActionFromMenu("delete")}
          sx={{ color: "#C45C5C" }}
        >
          작업 삭제
        </MenuItem>
      </Menu>

      <Dialog
        open={previewOpen}
        onClose={() => setPreviewOpen(false)}
        fullWidth
        maxWidth="xl"
        scroll="paper"
        slotProps={{
          paper: {
            sx: {
              backgroundColor: "#121416",
              minHeight: isMobilePreview ? "72vh" : "78vh",
            },
          },
        }}
      >
        <DialogTitle sx={{ color: "#FFFFFF", borderBottom: "1px solid rgba(231,227,227,0.08)", py: 1.5 }}>
          <Box sx={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 1.5 }}>
            <Box>
              <Typography variant="subtitle1" sx={{ color: "#FFFFFF", fontWeight: 700 }}>
                문항 미리보기 · {previewTitle}
              </Typography>
              <Typography variant="caption" sx={{ color: "#919497" }}>
                번호 패턴 기반 분리 + AI 분류 결과 결합
              </Typography>
            </Box>
            {!previewLoading && !previewError && (
              <Chip
                size="small"
                label={`${previewQuestions.length}문항`}
                sx={{
                  color: "#7FB3FF",
                  backgroundColor: "rgba(127,179,255,0.14)",
                  fontWeight: 600,
                }}
              />
            )}
          </Box>
        </DialogTitle>
        <DialogContent dividers sx={{ p: 0, borderColor: "rgba(231,227,227,0.08)" }}>
          {previewLoading && <Typography sx={{ color: "#919497" }}>불러오는 중...</Typography>}
          {!previewLoading && previewError && <Alert severity="warning">{previewError}</Alert>}
          {!previewLoading && !previewError && (
            <MathJaxContext config={mathJaxConfig}>
              <Box
                sx={{
                  display: "grid",
                  gridTemplateColumns: isMobilePreview ? "1fr" : "320px 1fr",
                  minHeight: isMobilePreview ? "auto" : 560,
                }}
              >
                <Box
                  sx={{
                    borderRight: isMobilePreview ? "none" : "1px solid rgba(231,227,227,0.08)",
                    borderBottom: isMobilePreview ? "1px solid rgba(231,227,227,0.08)" : "none",
                    maxHeight: isMobilePreview ? 220 : 560,
                    overflowY: "auto",
                    p: 1,
                  }}
                >
                  {previewQuestions.map((question, index) => {
                    const selected = index === previewSelectedIndex;
                    const snippet = question.statement_text.replace(/\s+/g, " ").trim();
                    return (
                      <Button
                        key={`${question.page_id}-${question.candidate_no}-${index}`}
                        onClick={() => setPreviewSelectedIndex(index)}
                        sx={{
                          width: "100%",
                          textAlign: "left",
                          justifyContent: "flex-start",
                          mb: 0.75,
                          px: 1.25,
                          py: 1,
                          borderRadius: 1.5,
                          border: "1px solid",
                          borderColor: selected ? "rgba(127,179,255,0.55)" : "rgba(231,227,227,0.08)",
                          backgroundColor: selected ? "rgba(127,179,255,0.12)" : "rgba(255,255,255,0.02)",
                          color: selected ? "#FFFFFF" : "#D3D6D9",
                          "&:hover": {
                            borderColor: "rgba(127,179,255,0.65)",
                            backgroundColor: "rgba(127,179,255,0.1)",
                          },
                        }}
                      >
                        <Box sx={{ width: "100%" }}>
                          <Box
                            sx={{
                              display: "flex",
                              alignItems: "center",
                              justifyContent: "space-between",
                              gap: 1,
                              mb: 0.4,
                            }}
                          >
                            <Typography variant="caption" sx={{ color: selected ? "#7FB3FF" : "#A7B5BF", fontWeight: 700 }}>
                              {question.candidate_key}
                            </Typography>
                            {question.has_visual_asset && (
                              <Chip
                                size="small"
                                label="시각요소"
                                sx={{
                                  height: 18,
                                  fontSize: 10,
                                  color: "#D4A574",
                                  backgroundColor: "rgba(212,165,116,0.15)",
                                }}
                              />
                            )}
                          </Box>
                          <Typography
                            variant="body2"
                            sx={{
                              fontSize: 12,
                              color: selected ? "#F2F4F6" : "#C1C5C9",
                              lineHeight: 1.5,
                              display: "-webkit-box",
                              WebkitLineClamp: 2,
                              WebkitBoxOrient: "vertical",
                              overflow: "hidden",
                              textOverflow: "ellipsis",
                            }}
                          >
                            {snippet || "(본문 없음)"}
                          </Typography>
                        </Box>
                      </Button>
                    );
                  })}
                </Box>

                <Box sx={{ p: { xs: 2, md: 3 }, overflowY: "auto" }}>
                  {!selectedPreviewQuestion && (
                    <Typography variant="body2" sx={{ color: "#919497" }}>
                      선택된 문항이 없습니다.
                    </Typography>
                  )}
                  {selectedPreviewQuestion && (
                    <>
                      <Box sx={{ display: "flex", flexWrap: "wrap", gap: 0.75, mb: 2 }}>
                        <Chip
                          size="small"
                          label={`페이지 ${selectedPreviewQuestion.page_no}`}
                          sx={{ color: "#E7E3E3", backgroundColor: "rgba(231,227,227,0.08)" }}
                        />
                        <Chip
                          size="small"
                          label={`문항 ${selectedPreviewQuestion.candidate_no}`}
                          sx={{ color: "#E7E3E3", backgroundColor: "rgba(231,227,227,0.08)" }}
                        />
                        <Chip
                          size="small"
                          label={`분리: ${selectedPreviewQuestion.split_strategy}`}
                          sx={{ color: "#A7B5BF", backgroundColor: "rgba(167,181,191,0.12)" }}
                        />
                        {selectedPreviewQuestion.confidence !== null && (
                          <Chip
                            size="small"
                            label={`신뢰도 ${Number(selectedPreviewQuestion.confidence).toFixed(0)}`}
                            sx={{ color: "#7FB3FF", backgroundColor: "rgba(127,179,255,0.14)" }}
                          />
                        )}
                        {selectedPreviewQuestion.provider && (
                          <Chip
                            size="small"
                            label={`AI ${selectedPreviewQuestion.provider}`}
                            sx={{ color: "#7FB3FF", backgroundColor: "rgba(127,179,255,0.14)" }}
                          />
                        )}
                        {selectedPreviewQuestion.asset_types.map((assetType) => (
                          <Chip
                            key={`${selectedPreviewQuestion.candidate_key}-${assetType}`}
                            size="small"
                            label={assetType}
                            sx={{ color: "#D4A574", backgroundColor: "rgba(212,165,116,0.14)" }}
                          />
                        ))}
                      </Box>

                      {selectedPreviewQuestion.has_visual_asset && selectedPreviewQuestion.asset_previews.length > 0 && (
                        <Alert severity="info" sx={{ mb: 2 }}>
                          그림/그래프/표가 문항과 함께 렌더링됩니다. 누락이 있으면 재동기화 후 재확인하세요.
                        </Alert>
                      )}
                      {selectedPreviewQuestion.has_visual_asset && selectedPreviewQuestion.asset_previews.length === 0 && (
                        <Alert severity="warning" sx={{ mb: 2 }}>
                          시각 요소는 감지됐지만 추출 이미지가 없습니다. `문제 적재`를 다시 실행하면 자산을 재생성합니다.
                        </Alert>
                      )}

                      <Box
                        sx={{
                          p: { xs: 2, md: 3 },
                          border: "1px solid rgba(231,227,227,0.1)",
                          borderRadius: 2,
                          background:
                            "linear-gradient(180deg, rgba(255,255,255,0.03) 0%, rgba(255,255,255,0.015) 100%)",
                          minHeight: 360,
                        }}
                      >
                        <ProblemStatementView
                          text={selectedPreviewQuestion.statement_text}
                          assets={selectedPreviewQuestion.asset_previews}
                        />
                      </Box>
                    </>
                  )}
                </Box>
              </Box>
            </MathJaxContext>
          )}
        </DialogContent>
        <DialogActions sx={{ borderTop: "1px solid rgba(231,227,227,0.08)", justifyContent: "space-between", px: 2 }}>
          <Typography variant="caption" sx={{ color: "#6D7880" }}>
            문항 경계는 번호 패턴 우선, AI 분류 결과가 있으면 해당 분할을 우선합니다.
          </Typography>
          <Button onClick={() => setPreviewOpen(false)} sx={{ color: "#E7E3E3" }}>
            닫기
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
