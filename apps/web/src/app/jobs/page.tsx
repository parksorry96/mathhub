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
  InputAdornment,
  LinearProgress,
  MenuItem,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from "@mui/material";
import SearchRoundedIcon from "@mui/icons-material/SearchRounded";
import PlayArrowRoundedIcon from "@mui/icons-material/PlayArrowRounded";
import VisibilityRoundedIcon from "@mui/icons-material/VisibilityRounded";
import DeleteOutlineRoundedIcon from "@mui/icons-material/DeleteOutlineRounded";
import RefreshRoundedIcon from "@mui/icons-material/RefreshRounded";
import { MathJaxContext } from "better-react-mathjax";
import { ProblemStatementView } from "@/components/problem-statement-view";
import type {
  ApiJobStatus,
  OcrJobListItem,
  OcrPagePreviewItem,
  OcrQuestionPreviewItem,
} from "@/lib/api";
import {
  deleteOcrJob,
  listOcrJobPages,
  listOcrJobQuestions,
  listOcrJobs,
  runOcrWorkflow,
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

const mathJaxConfig = {
  tex: {
    inlineMath: [["\\(", "\\)"], ["$", "$"]],
    displayMath: [["\\[", "\\]"], ["$$", "$$"]],
    processEscapes: true,
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

function toNumber(text: string) {
  const value = Number(text);
  return Number.isFinite(value) ? value : 0;
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

    const score = matches.length;
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

function detectVisualAssetTypes(statementText: string): string[] {
  const detected = new Set<string>();
  for (const hint of VISUAL_HINT_PATTERNS) {
    if (hint.pattern.test(statementText)) {
      detected.add(hint.assetType);
    }
  }
  return Array.from(detected).sort();
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
  const [previewQuestions, setPreviewQuestions] = useState<OcrQuestionPreviewItem[]>([]);
  const [previewSelectedIndex, setPreviewSelectedIndex] = useState(0);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);

  const loadJobs = useCallback(
    async (search: string, status: FilterStatus, options?: { silent?: boolean }) => {
      const silent = options?.silent ?? false;
      if (!silent) {
        setLoading(true);
        setError(null);
      }
      try {
        const response = await listOcrJobs({
          limit: 200,
          offset: 0,
          q: search.trim() || undefined,
          status: status === "all" ? undefined : status,
        });
        setJobs(response.items);
        setTotal(response.total);
      } catch (err) {
        setError(err instanceof Error ? err.message : "작업 목록을 불러오지 못했습니다.");
      } finally {
        if (!silent) {
          setLoading(false);
        }
      }
    },
    [],
  );

  useEffect(() => {
    void loadJobs(searchText, statusFilter);
  }, [loadJobs, searchText, statusFilter]);

  const hasRunningJobs = useMemo(
    () => jobs.some((job) => ["queued", "uploading", "processing"].includes(job.status)) || Object.keys(runningAction).length > 0,
    [jobs, runningAction],
  );

  useEffect(() => {
    if (!hasRunningJobs) return;
    const timer = setInterval(() => {
      void loadJobs(searchText, statusFilter, { silent: true });
    }, 2500);
    return () => clearInterval(timer);
  }, [hasRunningJobs, loadJobs, searchText, statusFilter]);

  const handleRefresh = useCallback(async () => {
    await loadJobs(searchText, statusFilter);
  }, [loadJobs, searchText, statusFilter]);

  const setRowAction = useCallback((jobId: string, action: string | null) => {
    setRunningAction((prev) => {
      if (!action) {
        const next = { ...prev };
        delete next[jobId];
        return next;
      }
      return { ...prev, [jobId]: action };
    });
  }, []);

  const handleRunWorkflow = useCallback(
    async (job: OcrJobListItem) => {
      setError(null);
      setNotice(null);
      setRowAction(job.id, "워크플로우 실행 중");
      try {
        const result = await runOcrWorkflow(job.id, {});
        setNotice(
          `완료: 문항 ${result.processed_candidates}건 처리 · 삽입 ${result.inserted_count}건 · 업데이트 ${result.updated_count}건 · 그래프/자산 저장 ${result.stored_visual_assets}건`,
        );
        await loadJobs(searchText, statusFilter, { silent: true });
      } catch (err) {
        setError(err instanceof Error ? err.message : "워크플로우 실행에 실패했습니다.");
      } finally {
        setRowAction(job.id, null);
      }
    },
    [loadJobs, searchText, setRowAction, statusFilter],
  );

  const handlePreview = useCallback(
    async (job: OcrJobListItem) => {
      setPreviewOpen(true);
      setPreviewTitle(job.original_filename);
      setPreviewQuestions([]);
      setPreviewSelectedIndex(0);
      setPreviewError(null);
      setPreviewLoading(true);
      try {
        let questions: OcrQuestionPreviewItem[] = [];
        try {
          const questionRes = await listOcrJobQuestions(job.id, { limit: 500, offset: 0 });
          questions = questionRes.items;
        } catch (err) {
          if (!(err instanceof Error) || !err.message.includes("404")) {
            throw err;
          }
        }

        if (questions.length === 0) {
          const pagesRes = await listOcrJobPages(job.id, { limit: 500, offset: 0 });
          questions = toQuestionPreviewItemsFromPages(pagesRes.items);
        }

        setPreviewQuestions(questions);
        if (questions.length === 0) {
          setPreviewError("미리볼 문항이 없습니다. 워크플로우를 실행한 뒤 다시 시도하세요.");
        }
      } catch (err) {
        setPreviewError(err instanceof Error ? err.message : "미리보기를 불러오지 못했습니다.");
      } finally {
        setPreviewLoading(false);
      }
    },
    [],
  );

  const handleDelete = useCallback(
    async (job: OcrJobListItem) => {
      const ok = window.confirm(`작업을 삭제할까요?\n${job.original_filename}`);
      if (!ok) return;

      setError(null);
      setNotice(null);
      setRowAction(job.id, "삭제 중");
      try {
        const deleted = await deleteOcrJob(job.id, { delete_source: true });
        setNotice(deleted.source_deleted ? "작업과 원본 파일을 삭제했습니다." : "작업을 삭제했습니다.");
        await loadJobs(searchText, statusFilter, { silent: true });
      } catch (err) {
        setError(err instanceof Error ? err.message : "작업 삭제에 실패했습니다.");
      } finally {
        setRowAction(job.id, null);
      }
    },
    [loadJobs, searchText, setRowAction, statusFilter],
  );

  const selectedQuestion = previewQuestions[previewSelectedIndex] ?? null;

  return (
    <Box>
      <Box sx={{ mb: 3.5, display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 2 }}>
        <Box>
          <Typography variant="h4" sx={{ fontWeight: 700, color: "#FFFFFF" }}>
            작업 목록
          </Typography>
          <Typography variant="body2" sx={{ color: "#919497", mt: 0.5 }}>
            단일 워크플로우: Mathpix 전체 OCR → AI 분류 → 문제/그래프 크롭 저장
          </Typography>
        </Box>
        <Button
          variant="outlined"
          size="small"
          startIcon={<RefreshRoundedIcon />}
          onClick={() => void handleRefresh()}
          sx={{
            borderColor: "rgba(231,227,227,0.2)",
            color: "#E7E3E3",
            "&:hover": { borderColor: "#E7E3E3" },
          }}
        >
          새로고침
        </Button>
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

      <Card sx={{ mb: 2 }}>
        <CardContent sx={{ display: "grid", gridTemplateColumns: "1fr 200px", gap: 1.5 }}>
          <TextField
            size="small"
            placeholder="파일명/키워드 검색"
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
            InputProps={{
              startAdornment: (
                <InputAdornment position="start">
                  <SearchRoundedIcon sx={{ fontSize: 18 }} />
                </InputAdornment>
              ),
            }}
          />
          <TextField
            select
            size="small"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as FilterStatus)}
          >
            <MenuItem value="all">전체 상태</MenuItem>
            <MenuItem value="queued">대기</MenuItem>
            <MenuItem value="uploading">업로드</MenuItem>
            <MenuItem value="processing">진행중</MenuItem>
            <MenuItem value="completed">완료</MenuItem>
            <MenuItem value="failed">실패</MenuItem>
            <MenuItem value="cancelled">취소</MenuItem>
          </TextField>
        </CardContent>
      </Card>

      <Card>
        <CardContent sx={{ p: 0 }}>
          <Box sx={{ px: 3, py: 2, borderBottom: "1px solid rgba(231,227,227,0.06)", display: "flex", justifyContent: "space-between" }}>
            <Typography variant="subtitle2" sx={{ color: "#FFFFFF", fontWeight: 600 }}>
              작업 {total.toLocaleString()}건
            </Typography>
            {hasRunningJobs && (
              <Typography variant="caption" sx={{ color: "#919497" }}>
                실행 중 작업 자동 새로고침 중
              </Typography>
            )}
          </Box>
          <TableContainer>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>파일명</TableCell>
                  <TableCell>상태</TableCell>
                  <TableCell>진행률</TableCell>
                  <TableCell>페이지</TableCell>
                  <TableCell>AI</TableCell>
                  <TableCell>요청시각</TableCell>
                  <TableCell align="right">액션</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {jobs.map((job) => {
                  const statusInfo = statusConfig[job.status];
                  const running = runningAction[job.id];
                  return (
                    <TableRow key={job.id} sx={{ "&:hover": { backgroundColor: "rgba(255,255,255,0.02)" } }}>
                      <TableCell>
                        <Typography sx={{ color: "#FFFFFF", fontSize: 13, fontWeight: 500 }}>
                          {job.original_filename}
                        </Typography>
                        {running && (
                          <Typography variant="caption" sx={{ color: "#919497" }}>
                            {running}
                          </Typography>
                        )}
                      </TableCell>
                      <TableCell>
                        <Chip
                          label={statusInfo.label}
                          size="small"
                          sx={{
                            color: statusInfo.color,
                            backgroundColor: statusInfo.bg,
                            fontSize: 11,
                            height: 22,
                          }}
                        />
                      </TableCell>
                      <TableCell sx={{ minWidth: 120 }}>
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
                          {job.progress_pct}%
                        </Typography>
                      </TableCell>
                      <TableCell>
                        <Typography variant="body2" sx={{ fontSize: 12 }}>
                          {job.processed_pages}/{job.total_pages || 0}
                        </Typography>
                      </TableCell>
                      <TableCell>
                        <Typography variant="body2" sx={{ fontSize: 12 }}>
                          {job.ai_candidates_processed ?? 0}/{job.ai_total_candidates ?? 0}
                        </Typography>
                      </TableCell>
                      <TableCell>
                        <Typography variant="body2" sx={{ fontSize: 12 }}>
                          {formatDate(job.requested_at)}
                        </Typography>
                      </TableCell>
                      <TableCell align="right">
                        <Stack direction="row" spacing={0.75} justifyContent="flex-end">
                          <Button
                            size="small"
                            variant="outlined"
                            startIcon={<PlayArrowRoundedIcon />}
                            disabled={Boolean(running)}
                            onClick={() => void handleRunWorkflow(job)}
                            sx={{
                              borderColor: "rgba(119,140,134,0.4)",
                              color: "#778C86",
                              "&:hover": { borderColor: "#778C86", backgroundColor: "rgba(119,140,134,0.12)" },
                            }}
                          >
                            실행
                          </Button>
                          <Button
                            size="small"
                            variant="text"
                            startIcon={<VisibilityRoundedIcon />}
                            disabled={Boolean(running)}
                            onClick={() => void handlePreview(job)}
                            sx={{ color: "#919497" }}
                          >
                            미리보기
                          </Button>
                          <Button
                            size="small"
                            variant="text"
                            startIcon={<DeleteOutlineRoundedIcon />}
                            disabled={Boolean(running)}
                            onClick={() => void handleDelete(job)}
                            sx={{ color: "#C45C5C" }}
                          >
                            삭제
                          </Button>
                        </Stack>
                      </TableCell>
                    </TableRow>
                  );
                })}

                {!loading && jobs.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={7}>
                      <Typography variant="body2" sx={{ py: 3, color: "#919497" }}>
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

      <Dialog open={previewOpen} onClose={() => setPreviewOpen(false)} maxWidth="xl" fullWidth>
        <DialogTitle>{previewTitle || "문항 미리보기"}</DialogTitle>
        <DialogContent dividers sx={{ minHeight: 420, p: 0 }}>
          {previewLoading && (
            <Box sx={{ p: 3 }}>
              <Typography variant="body2" sx={{ color: "#666" }}>
                문항 미리보기를 불러오는 중입니다...
              </Typography>
            </Box>
          )}
          {!previewLoading && previewError && (
            <Box sx={{ p: 3 }}>
              <Alert severity="warning">{previewError}</Alert>
            </Box>
          )}
          {!previewLoading && !previewError && previewQuestions.length > 0 && (
            <Box sx={{ display: "grid", gridTemplateColumns: "300px 1fr", minHeight: 420 }}>
              <Box sx={{ borderRight: "1px solid #eee", overflowY: "auto", maxHeight: 580 }}>
                {previewQuestions.map((item, index) => (
                  <Box
                    key={`${item.page_id}-${item.candidate_index}-${index}`}
                    onClick={() => setPreviewSelectedIndex(index)}
                    sx={{
                      p: 2,
                      cursor: "pointer",
                      borderBottom: "1px solid #f2f2f2",
                      backgroundColor: index === previewSelectedIndex ? "rgba(0,0,0,0.04)" : "#fff",
                      "&:hover": { backgroundColor: "rgba(0,0,0,0.02)" },
                    }}
                  >
                    <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>
                      P{item.page_no} · 문항 {item.candidate_no}
                    </Typography>
                    <Typography variant="caption" sx={{ color: "#666" }}>
                      {item.split_strategy}
                    </Typography>
                    <Typography variant="body2" sx={{ mt: 1, color: "#444" }}>
                      {item.statement_text.slice(0, 90)}
                      {item.statement_text.length > 90 ? "..." : ""}
                    </Typography>
                    <Stack direction="row" spacing={0.5} sx={{ mt: 1, flexWrap: "wrap" }}>
                      {item.asset_types.map((assetType) => (
                        <Chip key={assetType} size="small" label={assetType} />
                      ))}
                    </Stack>
                  </Box>
                ))}
              </Box>
              <Box sx={{ p: 3, overflowY: "auto", maxHeight: 580 }}>
                {selectedQuestion && (
                  <>
                    <Typography variant="h6" sx={{ mb: 1.5 }}>
                      P{selectedQuestion.page_no} · 문항 {selectedQuestion.candidate_no}
                    </Typography>
                    <Typography variant="caption" sx={{ color: "#666", display: "block", mb: 2 }}>
                      전략: {selectedQuestion.split_strategy}
                    </Typography>
                    <MathJaxContext config={mathJaxConfig}>
                      <ProblemStatementView
                        text={selectedQuestion.statement_text}
                        assets={selectedQuestion.asset_previews.map((asset, idx) => ({
                          id: `${selectedQuestion.external_problem_key}-${idx}`,
                          asset_type: asset.asset_type,
                          storage_key: asset.storage_key,
                          preview_url: asset.preview_url,
                          page_no: asset.page_no,
                          bbox: asset.bbox,
                        }))}
                      />
                    </MathJaxContext>
                  </>
                )}
              </Box>
            </Box>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setPreviewOpen(false)}>닫기</Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
