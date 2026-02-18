"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Card,
  CardContent,
  Chip,
  FormControl,
  IconButton,
  InputAdornment,
  MenuItem,
  Select,
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
import EditRoundedIcon from "@mui/icons-material/EditRounded";
import { listProblems, type ProblemListItem } from "@/lib/api";

type DifficultyFilter = "all" | "easy" | "medium" | "hard";
type ReviewFilter = "all" | "pending" | "approved" | "rejected";
type DifficultyLevel = "easy" | "medium" | "hard";

const difficultyConfig = {
  easy: { label: "2점", color: "#778C86", bg: "rgba(119,140,134,0.12)" },
  medium: { label: "3점", color: "#E7E3E3", bg: "rgba(231,227,227,0.08)" },
  hard: { label: "4점", color: "#C45C5C", bg: "rgba(196,92,92,0.12)" },
};

const statusLabels: Record<ReviewFilter, { label: string; color: string; bg: string }> = {
  all: { label: "전체", color: "#919497", bg: "rgba(145,148,151,0.1)" },
  approved: { label: "확정", color: "#778C86", bg: "rgba(119,140,134,0.12)" },
  pending: { label: "검수대기", color: "#D4A574", bg: "rgba(212,165,116,0.12)" },
  rejected: { label: "반려", color: "#C45C5C", bg: "rgba(196,92,92,0.12)" },
};

const selectSx = {
  backgroundColor: "#141414",
  fontSize: 13,
  height: 36,
  "& .MuiOutlinedInput-notchedOutline": {
    borderColor: "rgba(231,227,227,0.08)",
  },
  "&:hover .MuiOutlinedInput-notchedOutline": {
    borderColor: "rgba(231,227,227,0.15)",
  },
  "&.Mui-focused .MuiOutlinedInput-notchedOutline": {
    borderColor: "#E7E3E3",
  },
  "& .MuiSelect-select": { color: "#FFFFFF", py: 1 },
  "& .MuiSvgIcon-root": { color: "#919497" },
};

function pointToDifficulty(point: number): DifficultyLevel {
  if (point <= 2) return "easy";
  if (point === 3) return "medium";
  return "hard";
}

export default function ProblemsPage() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchText, setSearchText] = useState("");
  const [difficulty, setDifficulty] = useState<DifficultyFilter>("all");
  const [reviewStatus, setReviewStatus] = useState<ReviewFilter>("all");
  const [items, setItems] = useState<ProblemListItem[]>([]);
  const [total, setTotal] = useState(0);

  const loadProblems = useCallback(async (query: string, review: ReviewFilter) => {
    setLoading(true);
    setError(null);
    try {
      const res = await listProblems({
        limit: 200,
        offset: 0,
        q: query || undefined,
        review_status: review === "all" ? undefined : review,
      });
      setItems(res.items);
      setTotal(res.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : "문제 목록을 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const timer = setTimeout(() => {
      void loadProblems(searchText.trim(), reviewStatus);
    }, 250);
    return () => clearTimeout(timer);
  }, [searchText, reviewStatus, loadProblems]);

  const filtered = useMemo(() => {
    if (difficulty === "all") return items;
    return items.filter((item) => pointToDifficulty(item.point_value) === difficulty);
  }, [difficulty, items]);

  return (
    <Box>
      <Box sx={{ mb: 4 }}>
        <Typography variant="h4" sx={{ fontWeight: 700, color: "#FFFFFF" }}>
          문제 라이브러리
        </Typography>
        <Typography variant="body2" sx={{ color: "#919497", mt: 0.5 }}>
          실제 API(`GET /problems`) 데이터
        </Typography>
      </Box>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}

      <Box sx={{ mb: 3, display: "flex", gap: 1.5, alignItems: "center", flexWrap: "wrap" }}>
        <TextField
          size="small"
          placeholder="문제 내용 검색..."
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
        <FormControl size="small">
          <Select value={difficulty} onChange={(e) => setDifficulty(e.target.value as DifficultyFilter)} sx={selectSx}>
            <MenuItem value="all">전체 난이도</MenuItem>
            <MenuItem value="easy">2점</MenuItem>
            <MenuItem value="medium">3점</MenuItem>
            <MenuItem value="hard">4점</MenuItem>
          </Select>
        </FormControl>
        <FormControl size="small">
          <Select value={reviewStatus} onChange={(e) => setReviewStatus(e.target.value as ReviewFilter)} sx={selectSx}>
            <MenuItem value="all">전체 상태</MenuItem>
            <MenuItem value="approved">확정</MenuItem>
            <MenuItem value="pending">검수대기</MenuItem>
            <MenuItem value="rejected">반려</MenuItem>
          </Select>
        </FormControl>
        <Typography variant="caption" sx={{ color: "#919497" }}>
          총 {total.toLocaleString()}건 / 표시 {filtered.length.toLocaleString()}건
        </Typography>
      </Box>

      <Card>
        <CardContent sx={{ p: 0 }}>
          <TableContainer>
            <Table>
              <TableHead>
                <TableRow>
                  <TableCell sx={{ width: 60 }}>#</TableCell>
                  <TableCell>문제 내용</TableCell>
                  <TableCell>난이도</TableCell>
                  <TableCell>태그</TableCell>
                  <TableCell>출처</TableCell>
                  <TableCell>상태</TableCell>
                  <TableCell align="right" />
                </TableRow>
              </TableHead>
              <TableBody>
                {filtered.map((prob) => {
                  const diff = difficultyConfig[pointToDifficulty(prob.point_value)];
                  const status = statusLabels[(prob.review_status as ReviewFilter) ?? "pending"];
                  const tags = [prob.subject_name_ko, prob.unit_name_ko].filter(Boolean) as string[];
                  return (
                    <TableRow key={prob.id} sx={{ "&:hover": { backgroundColor: "rgba(255,255,255,0.02)" } }}>
                      <TableCell>
                        <Typography variant="body2" sx={{ color: "#919497", fontSize: 13 }}>
                          {prob.source_problem_label ?? "—"}
                        </Typography>
                      </TableCell>
                      <TableCell sx={{ maxWidth: 420 }}>
                        <Typography
                          variant="body2"
                          sx={{
                            color: "#FFFFFF",
                            fontWeight: 500,
                            fontSize: 13,
                            overflow: "hidden",
                            textOverflow: "ellipsis",
                            whiteSpace: "nowrap",
                          }}
                        >
                          {prob.content || "(본문 없음)"}
                        </Typography>
                      </TableCell>
                      <TableCell>
                        <Chip
                          label={diff.label}
                          size="small"
                          sx={{
                            color: diff.color,
                            backgroundColor: diff.bg,
                            fontWeight: 500,
                            fontSize: 11,
                            height: 22,
                          }}
                        />
                      </TableCell>
                      <TableCell>
                        <Box sx={{ display: "flex", gap: 0.5, flexWrap: "wrap" }}>
                          {tags.length > 0 ? (
                            tags.map((tag) => (
                              <Chip
                                key={tag}
                                label={tag}
                                size="small"
                                variant="outlined"
                                sx={{
                                  borderColor: "rgba(231,227,227,0.1)",
                                  color: "#919497",
                                  fontSize: 11,
                                  height: 20,
                                }}
                              />
                            ))
                          ) : (
                            <Typography variant="caption" sx={{ color: "#52525B" }}>
                              —
                            </Typography>
                          )}
                        </Box>
                      </TableCell>
                      <TableCell>
                        <Typography variant="body2" sx={{ color: "#919497", fontSize: 12 }}>
                          {prob.source_title ?? prob.document_filename ?? "미지정"}
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
                      <TableCell align="right">
                        <IconButton size="small" sx={{ color: "#919497" }}>
                          <EditRoundedIcon sx={{ fontSize: 16 }} />
                        </IconButton>
                      </TableCell>
                    </TableRow>
                  );
                })}
                {!loading && filtered.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={7}>
                      <Typography variant="body2" sx={{ color: "#919497", py: 2 }}>
                        조건에 맞는 문제가 없습니다.
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
