"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
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
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import SearchRoundedIcon from "@mui/icons-material/SearchRounded";
import RefreshRoundedIcon from "@mui/icons-material/RefreshRounded";
import CloudUploadRoundedIcon from "@mui/icons-material/CloudUploadRounded";
import SmartToyRoundedIcon from "@mui/icons-material/SmartToyRounded";
import PlaylistAddCheckRoundedIcon from "@mui/icons-material/PlaylistAddCheckRounded";
import DeleteOutlineRoundedIcon from "@mui/icons-material/DeleteOutlineRounded";
import VisibilityRoundedIcon from "@mui/icons-material/VisibilityRounded";
import { MathJax, MathJaxContext } from "better-react-mathjax";
import type { ApiJobStatus, OcrJobListItem, OcrPagePreviewItem } from "@/lib/api";
import {
  classifyOcrJobStep,
  deleteOcrJob,
  listOcrJobPages,
  listOcrJobs,
  materializeProblems,
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

export default function JobsPage() {
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
  const [previewPages, setPreviewPages] = useState<OcrPagePreviewItem[]>([]);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);

  const loadJobs = useCallback(
    async (search: string, status: FilterStatus) => {
      setLoading(true);
      setError(null);
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
        setError(err instanceof Error ? err.message : "작업 목록을 불러오지 못했습니다.");
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  useEffect(() => {
    const timer = setTimeout(() => {
      void loadJobs(searchText.trim(), statusFilter);
    }, 250);
    return () => clearTimeout(timer);
  }, [searchText, statusFilter, loadJobs]);

  const runAction = useCallback(
    async (job: OcrJobListItem, action: "submit" | "sync" | "classify" | "materialize" | "delete") => {
      setNotice(null);
      setError(null);
      setRunningAction((prev) => ({ ...prev, [job.id]: action }));
      try {
        if (action === "submit") {
          await submitMathpixJob(job.id, {});
          setNotice(`${job.original_filename}: Mathpix 제출 완료`);
        } else if (action === "sync") {
          await syncMathpixJob(job.id, {});
          setNotice(`${job.original_filename}: Mathpix 상태 동기화 완료`);
        } else if (action === "classify") {
          let latest: {
            done: boolean;
            total_candidates: number;
            candidates_processed: number;
            provider: string;
            model: string;
          } | null = null;
          let attempts = 0;
          const maxAttempts = 3000;
          while (attempts < maxAttempts) {
            const step = await classifyOcrJobStep(job.id, { max_pages: 50, min_confidence: 0 });
            latest = step;
            if (!step.done) {
              const at = step.current_page_no && step.current_candidate_no ? ` (P${step.current_page_no}-C${step.current_candidate_no})` : "";
              setNotice(
                `${job.original_filename}: AI 분류 진행중 ${step.candidates_processed}/${step.total_candidates}${at}`,
              );
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
        await loadJobs(searchText.trim(), statusFilter);
      } catch (err) {
        setError(err instanceof Error ? err.message : "작업 실행에 실패했습니다.");
      } finally {
        setRunningAction((prev) => {
          const next = { ...prev };
          delete next[job.id];
          return next;
        });
      }
    },
    [loadJobs, searchText, statusFilter],
  );

  const openPreview = useCallback(async (job: OcrJobListItem) => {
    setPreviewOpen(true);
    setPreviewTitle(job.original_filename);
    setPreviewPages([]);
    setPreviewError(null);
    setPreviewLoading(true);
    try {
      const res = await listOcrJobPages(job.id, { limit: 50, offset: 0 });
      setPreviewPages(res.items);
      if (res.items.length === 0) {
        setPreviewError("아직 추출된 OCR 페이지가 없습니다. Mathpix 동기화를 먼저 실행하세요.");
      }
    } catch (err) {
      setPreviewError(err instanceof Error ? err.message : "OCR 페이지를 불러오지 못했습니다.");
    } finally {
      setPreviewLoading(false);
    }
  }, []);

  const visibleStatuses = useMemo(
    () => ["completed", "processing", "uploading", "queued", "failed", "cancelled"] as ApiJobStatus[],
    [],
  );

  return (
    <Box>
      <Box sx={{ mb: 4 }}>
        <Typography variant="h4" sx={{ fontWeight: 700, color: "#FFFFFF" }}>
          작업 목록
        </Typography>
        <Typography variant="body2" sx={{ color: "#919497", mt: 0.5 }}>
          실제 API 연동 상태 관리 (제출/동기화/AI 분류/문제 적재)
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
                  const submitDisabled = Boolean(busy) || !!job.provider_job_id || !submitSourceSupported;
                  const aiTotal = job.ai_total_candidates ?? 0;
                  const aiProcessed = job.ai_candidates_processed ?? 0;
                  const aiAccepted = job.ai_candidates_accepted ?? 0;
                  const hasAiProgress =
                    job.ai_done !== null ||
                    job.ai_total_candidates !== null ||
                    job.ai_candidates_processed !== null;
                  const submitTooltip = busy
                    ? "실행 중"
                    : !submitSourceSupported
                      ? "이 작업은 legacy storage_key(upload://)라 제출할 수 없습니다. 새로 업로드 후 시도하세요."
                      : "Mathpix 제출";
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
                          <Tooltip title={busy ? "실행 중" : "OCR 미리보기"}>
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
                          <Tooltip title={submitTooltip}>
                            <span>
                              <IconButton
                                size="small"
                                sx={{ color: "#919497" }}
                                disabled={submitDisabled}
                                onClick={() => void runAction(job, "submit")}
                              >
                                <CloudUploadRoundedIcon sx={{ fontSize: 16 }} />
                              </IconButton>
                            </span>
                          </Tooltip>
                          <Tooltip title={busy ? "실행 중" : "Mathpix 동기화"}>
                            <span>
                              <IconButton
                                size="small"
                                sx={{ color: "#919497" }}
                                disabled={Boolean(busy) || !job.provider_job_id}
                                onClick={() => void runAction(job, "sync")}
                              >
                                <RefreshRoundedIcon sx={{ fontSize: 16 }} />
                              </IconButton>
                            </span>
                          </Tooltip>
                          <Tooltip title={busy ? "실행 중" : "AI 분류"}>
                            <span>
                              <IconButton
                                size="small"
                                sx={{ color: "#919497" }}
                                disabled={Boolean(busy)}
                                onClick={() => void runAction(job, "classify")}
                              >
                                <SmartToyRoundedIcon sx={{ fontSize: 16 }} />
                              </IconButton>
                            </span>
                          </Tooltip>
                          <Tooltip title={busy ? "실행 중" : "문제 적재"}>
                            <span>
                              <IconButton
                                size="small"
                                sx={{ color: "#919497" }}
                                disabled={Boolean(busy)}
                                onClick={() => void runAction(job, "materialize")}
                              >
                                <PlaylistAddCheckRoundedIcon sx={{ fontSize: 16 }} />
                              </IconButton>
                            </span>
                          </Tooltip>
                          <Tooltip title={busy ? "실행 중" : "작업 삭제"}>
                            <span>
                              <IconButton
                                size="small"
                                sx={{ color: "#C45C5C" }}
                                disabled={Boolean(busy)}
                                onClick={() => {
                                  const ok = window.confirm(
                                    "이 작업을 삭제할까요?\n(참조가 없으면 원본 S3 파일도 함께 삭제 시도됩니다.)",
                                  );
                                  if (ok) {
                                    void runAction(job, "delete");
                                  }
                                }}
                              >
                                <DeleteOutlineRoundedIcon sx={{ fontSize: 16 }} />
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

      <Dialog
        open={previewOpen}
        onClose={() => setPreviewOpen(false)}
        fullWidth
        maxWidth="md"
        PaperProps={{ sx: { backgroundColor: "#18181A" } }}
      >
        <DialogTitle sx={{ color: "#FFFFFF", borderBottom: "1px solid rgba(231,227,227,0.08)" }}>
          OCR 미리보기 · {previewTitle}
        </DialogTitle>
        <DialogContent sx={{ pt: 2 }}>
          {previewLoading && <Typography sx={{ color: "#919497" }}>불러오는 중...</Typography>}
          {!previewLoading && previewError && <Alert severity="warning">{previewError}</Alert>}
          {!previewLoading && !previewError && (
            <MathJaxContext config={mathJaxConfig}>
              {previewPages.map((page) => (
                <Box
                  key={page.id}
                  sx={{
                    mb: 2,
                    p: 2,
                    border: "1px solid rgba(231,227,227,0.08)",
                    borderRadius: 1.5,
                    backgroundColor: "rgba(255,255,255,0.02)",
                  }}
                >
                  <Typography variant="subtitle2" sx={{ color: "#E7E3E3", mb: 1 }}>
                    페이지 {page.page_no}
                  </Typography>
                  <Box
                    sx={{
                      color: "#CFCFCF",
                      whiteSpace: "pre-wrap",
                      fontFamily: "monospace",
                      fontSize: 12,
                      lineHeight: 1.7,
                    }}
                  >
                    <MathJax dynamic>
                      {(page.extracted_text || page.extracted_latex || "").trim() || "(추출 텍스트 없음)"}
                    </MathJax>
                  </Box>
                </Box>
              ))}
            </MathJaxContext>
          )}
        </DialogContent>
        <DialogActions sx={{ borderTop: "1px solid rgba(231,227,227,0.08)" }}>
          <Button onClick={() => setPreviewOpen(false)} sx={{ color: "#E7E3E3" }}>
            닫기
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
