"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Card,
  CardContent,
  Chip,
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
import type { ApiJobStatus, OcrJobListItem } from "@/lib/api";
import {
  classifyOcrJob,
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
    async (job: OcrJobListItem, action: "submit" | "sync" | "classify" | "materialize") => {
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
          await classifyOcrJob(job.id, { max_pages: 50, min_confidence: 0 });
          setNotice(`${job.original_filename}: AI 분류 완료`);
        } else {
          await materializeProblems(job.id, {
            curriculum_code: "CSAT_2027",
            min_confidence: 0,
            default_point_value: 3,
            default_response_type: "short_answer",
            default_answer_key: "PENDING_REVIEW",
          });
          setNotice(`${job.original_filename}: 문제은행 적재 완료`);
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
    </Box>
  );
}
