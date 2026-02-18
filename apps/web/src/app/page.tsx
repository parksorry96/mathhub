"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Box,
  Card,
  CardContent,
  Typography,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Chip,
  LinearProgress,
  IconButton,
  Button,
  Alert,
} from "@mui/material";
import TrendingUpRoundedIcon from "@mui/icons-material/TrendingUpRounded";
import CloudUploadRoundedIcon from "@mui/icons-material/CloudUploadRounded";
import VisibilityRoundedIcon from "@mui/icons-material/VisibilityRounded";
import RefreshRoundedIcon from "@mui/icons-material/RefreshRounded";
import { ApiJobStatus, listOcrJobs, listProblems, type OcrJobListItem } from "@/lib/api";
import { useRouter } from "next/navigation";

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

export default function DashboardPage() {
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [jobs, setJobs] = useState<OcrJobListItem[]>([]);
  const [jobStatusCounts, setJobStatusCounts] = useState<Record<ApiJobStatus, number>>({
    queued: 0,
    uploading: 0,
    processing: 0,
    completed: 0,
    failed: 0,
    cancelled: 0,
  });
  const [totalProblems, setTotalProblems] = useState(0);
  const [pendingReview, setPendingReview] = useState(0);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [jobsRes, problemsRes] = await Promise.all([
        listOcrJobs({ limit: 5, offset: 0 }),
        listProblems({ limit: 1, offset: 0 }),
      ]);
      setJobs(jobsRes.items);
      setJobStatusCounts(jobsRes.status_counts);
      setTotalProblems(problemsRes.total);
      setPendingReview(problemsRes.review_counts.pending ?? 0);
    } catch (err) {
      setError(err instanceof Error ? err.message : "데이터를 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  const activeJobs = useMemo(
    () =>
      (jobStatusCounts.queued ?? 0) +
      (jobStatusCounts.uploading ?? 0) +
      (jobStatusCounts.processing ?? 0),
    [jobStatusCounts],
  );

  const successRate = useMemo(() => {
    const completed = jobStatusCounts.completed ?? 0;
    const failed = (jobStatusCounts.failed ?? 0) + (jobStatusCounts.cancelled ?? 0);
    const denominator = completed + failed;
    if (denominator === 0) return 0;
    return Number(((completed / denominator) * 100).toFixed(1));
  }, [jobStatusCounts]);

  const statCards = [
    {
      label: "총 문제 수",
      value: totalProblems.toLocaleString(),
      sub: `승인 ${jobStatusCounts.completed ?? 0}건 OCR 완료`,
      accent: "#FFFFFF",
    },
    {
      label: "진행 중 작업",
      value: activeJobs,
      sub: `대기 ${(jobStatusCounts.queued ?? 0).toLocaleString()}건`,
      accent: "#E7E3E3",
    },
    {
      label: "검수 대기",
      value: pendingReview,
      sub: "검수 큐에서 승인/반려 처리",
      accent: "#919497",
    },
    {
      label: "OCR 성공률",
      value: `${successRate}%`,
      sub: "완료/(완료+실패+취소)",
      accent: "#778C86",
    },
  ];

  return (
    <Box>
      <Box sx={{ mb: 4, display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <Box>
          <Typography variant="h4" sx={{ fontWeight: 700, color: "#FFFFFF" }}>
            대시보드
          </Typography>
          <Typography variant="body2" sx={{ color: "#919497", mt: 0.5 }}>
            실제 API 데이터 기반 운영 현황
          </Typography>
        </Box>
        <Button
          size="small"
          variant="outlined"
          startIcon={<RefreshRoundedIcon />}
          onClick={() => void loadData()}
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
        <Alert severity="error" sx={{ mb: 3 }}>
          {error}
        </Alert>
      )}

      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: "repeat(4, 1fr)",
          gap: 2.5,
          mb: 4,
        }}
      >
        {statCards.map((card) => (
          <Card key={card.label}>
            <CardContent sx={{ p: 3, "&:last-child": { pb: 3 } }}>
              <Typography
                variant="caption"
                sx={{
                  color: "#919497",
                  fontWeight: 500,
                  textTransform: "uppercase",
                  letterSpacing: "0.05em",
                  fontSize: "0.7rem",
                }}
              >
                {card.label}
              </Typography>
              <Typography
                variant="h3"
                sx={{
                  fontWeight: 700,
                  color: card.accent,
                  mt: 1,
                  mb: 0.5,
                  fontSize: "2rem",
                }}
              >
                {loading ? "..." : card.value}
              </Typography>
              <Box sx={{ display: "flex", alignItems: "center", gap: 0.5 }}>
                <TrendingUpRoundedIcon sx={{ fontSize: 14, color: "#778C86" }} />
                <Typography variant="caption" sx={{ color: "#778C86" }}>
                  {card.sub}
                </Typography>
              </Box>
            </CardContent>
          </Card>
        ))}
      </Box>

      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: "2fr 1fr",
          gap: 2.5,
        }}
      >
        <Card>
          <CardContent sx={{ p: 0 }}>
            <Box
              sx={{
                px: 3,
                py: 2,
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                borderBottom: "1px solid rgba(231,227,227,0.06)",
              }}
            >
              <Typography variant="subtitle2" sx={{ fontWeight: 600, color: "#FFFFFF" }}>
                최근 작업
              </Typography>
              <Typography
                variant="caption"
                onClick={() => router.push("/jobs")}
                sx={{
                  color: "#919497",
                  cursor: "pointer",
                  "&:hover": { color: "#FFFFFF" },
                }}
              >
                전체 보기 →
              </Typography>
            </Box>
            <TableContainer>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>파일명</TableCell>
                    <TableCell>상태</TableCell>
                    <TableCell>진행률</TableCell>
                    <TableCell>일시</TableCell>
                    <TableCell align="right" />
                  </TableRow>
                </TableHead>
                <TableBody>
                  {jobs.map((job) => {
                    const status = statusConfig[job.status];
                    return (
                      <TableRow key={job.id} sx={{ "&:hover": { backgroundColor: "rgba(255,255,255,0.02)" } }}>
                        <TableCell>
                          <Typography variant="body2" sx={{ color: "#FFFFFF", fontWeight: 500, fontSize: 13 }}>
                            {job.original_filename}
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
                        <TableCell sx={{ minWidth: 120 }}>
                          <LinearProgress
                            variant="determinate"
                            value={toNumber(job.progress_pct)}
                            sx={{
                              height: 4,
                              "& .MuiLinearProgress-bar": {
                                backgroundColor:
                                  job.status === "completed" ? "#778C86" : "#E7E3E3",
                              },
                            }}
                          />
                          <Typography variant="caption" sx={{ color: "#919497" }}>
                            {job.processed_pages}/{job.total_pages || 0} 페이지
                          </Typography>
                        </TableCell>
                        <TableCell>
                          <Typography variant="body2" sx={{ fontSize: 13 }}>
                            {formatDate(job.requested_at)}
                          </Typography>
                        </TableCell>
                        <TableCell align="right">
                          <IconButton
                            size="small"
                            sx={{ color: "#919497" }}
                            onClick={() => router.push("/jobs")}
                          >
                            <VisibilityRoundedIcon sx={{ fontSize: 16 }} />
                          </IconButton>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                  {!loading && jobs.length === 0 && (
                    <TableRow>
                      <TableCell colSpan={5}>
                        <Typography variant="body2" sx={{ color: "#919497", py: 2 }}>
                          등록된 작업이 없습니다.
                        </Typography>
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </TableContainer>
          </CardContent>
        </Card>

        <Card>
          <CardContent sx={{ p: 3, "&:last-child": { pb: 3 } }}>
            <Typography variant="subtitle2" sx={{ fontWeight: 600, color: "#FFFFFF", mb: 2 }}>
              빠른 업로드
            </Typography>
            <Box
              onClick={() => router.push("/upload")}
              sx={{
                border: "2px dashed rgba(231,227,227,0.12)",
                borderRadius: 3,
                p: 4,
                textAlign: "center",
                cursor: "pointer",
                transition: "all 0.2s",
                "&:hover": {
                  borderColor: "rgba(231,227,227,0.25)",
                  backgroundColor: "rgba(255,255,255,0.02)",
                },
              }}
            >
              <CloudUploadRoundedIcon sx={{ fontSize: 40, color: "#919497", mb: 1.5 }} />
              <Typography variant="body2" sx={{ color: "#E7E3E3", fontWeight: 500 }}>
                PDF 파일 업로드 후
              </Typography>
              <Typography variant="body2" sx={{ color: "#E7E3E3", fontWeight: 500 }}>
                OCR 파이프라인 시작
              </Typography>
              <Typography variant="caption" sx={{ color: "#52525B", display: "block", mt: 1 }}>
                실제 API 연동 상태
              </Typography>
            </Box>
          </CardContent>
        </Card>
      </Box>
    </Box>
  );
}
