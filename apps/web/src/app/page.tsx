"use client";

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
} from "@mui/material";
import TrendingUpRoundedIcon from "@mui/icons-material/TrendingUpRounded";
import CloudUploadRoundedIcon from "@mui/icons-material/CloudUploadRounded";
import VisibilityRoundedIcon from "@mui/icons-material/VisibilityRounded";
import { mockJobs, mockStats } from "@/mocks/data";
import type { OcrJobStatus } from "@mathhub/shared";

const statusConfig: Record<
  OcrJobStatus,
  { label: string; color: string; bg: string }
> = {
  completed: { label: "완료", color: "#778C86", bg: "rgba(119,140,134,0.12)" },
  running: { label: "진행중", color: "#E7E3E3", bg: "rgba(231,227,227,0.08)" },
  queued: { label: "대기", color: "#919497", bg: "rgba(145,148,151,0.1)" },
  partial: { label: "부분완료", color: "#D4A574", bg: "rgba(212,165,116,0.12)" },
  failed: { label: "실패", color: "#C45C5C", bg: "rgba(196,92,92,0.12)" },
};

const statCards = [
  {
    label: "총 문제 수",
    value: mockStats.totalProblems.toLocaleString(),
    sub: "+42 이번 주",
    accent: "#FFFFFF",
  },
  {
    label: "진행 중 작업",
    value: mockStats.activeJobs,
    sub: "2개 대기",
    accent: "#E7E3E3",
  },
  {
    label: "검수 대기",
    value: mockStats.pendingReview,
    sub: "3건 긴급",
    accent: "#919497",
  },
  {
    label: "OCR 성공률",
    value: `${mockStats.successRate}%`,
    sub: "+0.3% 전주 대비",
    accent: "#778C86",
  },
];

export default function DashboardPage() {
  return (
    <Box>
      {/* Page Header */}
      <Box sx={{ mb: 4 }}>
        <Typography variant="h4" sx={{ fontWeight: 700, color: "#FFFFFF" }}>
          대시보드
        </Typography>
        <Typography variant="body2" sx={{ color: "#919497", mt: 0.5 }}>
          문제 관리 현황을 한눈에 확인하세요
        </Typography>
      </Box>

      {/* Stats Cards */}
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
                {card.value}
              </Typography>
              <Box sx={{ display: "flex", alignItems: "center", gap: 0.5 }}>
                <TrendingUpRoundedIcon
                  sx={{ fontSize: 14, color: "#778C86" }}
                />
                <Typography variant="caption" sx={{ color: "#778C86" }}>
                  {card.sub}
                </Typography>
              </Box>
            </CardContent>
          </Card>
        ))}
      </Box>

      {/* Content Grid */}
      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: "2fr 1fr",
          gap: 2.5,
        }}
      >
        {/* Recent Jobs Table */}
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
                sx={{ color: "#919497", cursor: "pointer", "&:hover": { color: "#FFFFFF" } }}
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
                    <TableCell>페이지</TableCell>
                    <TableCell>일시</TableCell>
                    <TableCell align="right" />
                  </TableRow>
                </TableHead>
                <TableBody>
                  {mockJobs.map((job) => {
                    const status = statusConfig[job.status];
                    return (
                      <TableRow
                        key={job.id}
                        sx={{ "&:hover": { backgroundColor: "rgba(255,255,255,0.02)" } }}
                      >
                        <TableCell>
                          <Typography variant="body2" sx={{ color: "#FFFFFF", fontWeight: 500, fontSize: 13 }}>
                            {job.fileName}
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
                        <TableCell>
                          <Typography variant="body2" sx={{ fontSize: 13 }}>
                            {job.totalPages
                              ? `${job.processedPages}/${job.totalPages}`
                              : "—"}
                          </Typography>
                        </TableCell>
                        <TableCell>
                          <Typography variant="body2" sx={{ fontSize: 13 }}>
                            {job.createdAt}
                          </Typography>
                        </TableCell>
                        <TableCell align="right">
                          <IconButton size="small" sx={{ color: "#919497" }}>
                            <VisibilityRoundedIcon sx={{ fontSize: 16 }} />
                          </IconButton>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </TableContainer>
          </CardContent>
        </Card>

        {/* Quick Upload */}
        <Card>
          <CardContent sx={{ p: 3, "&:last-child": { pb: 3 } }}>
            <Typography variant="subtitle2" sx={{ fontWeight: 600, color: "#FFFFFF", mb: 2 }}>
              빠른 업로드
            </Typography>
            <Box
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
              <CloudUploadRoundedIcon
                sx={{ fontSize: 40, color: "#919497", mb: 1.5 }}
              />
              <Typography variant="body2" sx={{ color: "#E7E3E3", fontWeight: 500 }}>
                PDF 파일을 드래그하거나
              </Typography>
              <Typography variant="body2" sx={{ color: "#E7E3E3", fontWeight: 500 }}>
                클릭하여 업로드
              </Typography>
              <Typography
                variant="caption"
                sx={{ color: "#52525B", display: "block", mt: 1 }}
              >
                최대 50MB · PDF만 지원
              </Typography>
            </Box>

            {/* Progress sample */}
            <Box sx={{ mt: 3 }}>
              <Box
                sx={{
                  display: "flex",
                  justifyContent: "space-between",
                  mb: 0.5,
                }}
              >
                <Typography variant="caption" sx={{ color: "#E7E3E3", fontWeight: 500 }}>
                  고1_수학(상)_단원평가.pdf
                </Typography>
                <Typography variant="caption" sx={{ color: "#919497" }}>
                  62%
                </Typography>
              </Box>
              <LinearProgress
                variant="determinate"
                value={62}
                sx={{
                  "& .MuiLinearProgress-bar": {
                    backgroundColor: "#E7E3E3",
                  },
                }}
              />
            </Box>
          </CardContent>
        </Card>
      </Box>
    </Box>
  );
}
