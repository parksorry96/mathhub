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
  IconButton,
  TextField,
  InputAdornment,
  LinearProgress,
} from "@mui/material";
import SearchRoundedIcon from "@mui/icons-material/SearchRounded";
import VisibilityRoundedIcon from "@mui/icons-material/VisibilityRounded";
import ReplayRoundedIcon from "@mui/icons-material/ReplayRounded";
import { mockJobs } from "@/mocks/data";
import type { OcrJobStatus } from "@mathhub/shared";

const statusConfig: Record<
  OcrJobStatus,
  { label: string; color: string; bg: string }
> = {
  completed: { label: "완료", color: "#778C86", bg: "rgba(119,140,134,0.12)" },
  running: { label: "진행중", color: "#E7E3E3", bg: "rgba(231,227,227,0.08)" },
  queued: { label: "대기", color: "#919497", bg: "rgba(145,148,151,0.1)" },
  partial: {
    label: "부분완료",
    color: "#D4A574",
    bg: "rgba(212,165,116,0.12)",
  },
  failed: { label: "실패", color: "#C45C5C", bg: "rgba(196,92,92,0.12)" },
};

export default function JobsPage() {
  return (
    <Box>
      <Box sx={{ mb: 4 }}>
        <Typography variant="h4" sx={{ fontWeight: 700, color: "#FFFFFF" }}>
          작업 목록
        </Typography>
        <Typography variant="body2" sx={{ color: "#919497", mt: 0.5 }}>
          OCR 처리 작업의 상태를 확인하고 관리합니다
        </Typography>
      </Box>

      {/* Filters */}
      <Box sx={{ mb: 3, display: "flex", gap: 1.5, alignItems: "center" }}>
        <TextField
          size="small"
          placeholder="파일명 검색..."
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
            width: 300,
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
        {(["completed", "running", "queued", "failed"] as OcrJobStatus[]).map(
          (s) => (
            <Chip
              key={s}
              label={statusConfig[s].label}
              size="small"
              variant="outlined"
              sx={{
                borderColor: "rgba(231,227,227,0.12)",
                color: "#919497",
                fontSize: 12,
                "&:hover": {
                  borderColor: statusConfig[s].color,
                  color: statusConfig[s].color,
                },
              }}
            />
          )
        )}
      </Box>

      {/* Jobs Table */}
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
                {mockJobs.map((job) => {
                  const status = statusConfig[job.status];
                  const progress = job.totalPages
                    ? (job.processedPages / job.totalPages) * 100
                    : 0;

                  return (
                    <TableRow
                      key={job.id}
                      sx={{
                        "&:hover": {
                          backgroundColor: "rgba(255,255,255,0.02)",
                        },
                      }}
                    >
                      <TableCell>
                        <Typography
                          variant="body2"
                          sx={{
                            color: "#FFFFFF",
                            fontWeight: 500,
                            fontSize: 13,
                          }}
                        >
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
                      <TableCell sx={{ minWidth: 120 }}>
                        {job.totalPages ? (
                          <Box>
                            <Box
                              sx={{
                                display: "flex",
                                justifyContent: "space-between",
                                mb: 0.5,
                              }}
                            >
                              <Typography
                                variant="caption"
                                sx={{ color: "#919497" }}
                              >
                                {job.processedPages}/{job.totalPages} 페이지
                              </Typography>
                            </Box>
                            <LinearProgress
                              variant="determinate"
                              value={progress}
                              sx={{
                                height: 4,
                                "& .MuiLinearProgress-bar": {
                                  backgroundColor:
                                    job.status === "completed"
                                      ? "#778C86"
                                      : "#E7E3E3",
                                },
                              }}
                            />
                          </Box>
                        ) : (
                          <Typography
                            variant="body2"
                            sx={{ color: "#52525B", fontSize: 13 }}
                          >
                            —
                          </Typography>
                        )}
                      </TableCell>
                      <TableCell>
                        <Typography
                          variant="body2"
                          sx={{ color: "#919497", fontSize: 13 }}
                        >
                          {job.duration ?? "—"}
                        </Typography>
                      </TableCell>
                      <TableCell>
                        <Typography
                          variant="body2"
                          sx={{ color: "#919497", fontSize: 13 }}
                        >
                          {job.createdAt}
                        </Typography>
                      </TableCell>
                      <TableCell align="right">
                        <Box sx={{ display: "flex", justifyContent: "flex-end", gap: 0.5 }}>
                          <IconButton size="small" sx={{ color: "#919497" }}>
                            <VisibilityRoundedIcon sx={{ fontSize: 16 }} />
                          </IconButton>
                          {job.status === "failed" && (
                            <IconButton size="small" sx={{ color: "#C45C5C" }}>
                              <ReplayRoundedIcon sx={{ fontSize: 16 }} />
                            </IconButton>
                          )}
                        </Box>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </TableContainer>
        </CardContent>
      </Card>
    </Box>
  );
}
