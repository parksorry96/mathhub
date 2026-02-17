"use client";

import {
  Box,
  Card,
  CardContent,
  Typography,
  Chip,
  TextField,
  InputAdornment,
  Select,
  MenuItem,
  FormControl,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  IconButton,
} from "@mui/material";
import SearchRoundedIcon from "@mui/icons-material/SearchRounded";
import EditRoundedIcon from "@mui/icons-material/EditRounded";
import { mockProblems } from "@/mocks/data";
import type { ProblemDifficulty } from "@mathhub/shared";

const difficultyConfig: Record<
  ProblemDifficulty,
  { label: string; color: string; bg: string }
> = {
  easy: { label: "쉬움", color: "#778C86", bg: "rgba(119,140,134,0.12)" },
  medium: { label: "보통", color: "#E7E3E3", bg: "rgba(231,227,227,0.08)" },
  hard: { label: "어려움", color: "#C45C5C", bg: "rgba(196,92,92,0.12)" },
};

const statusLabels: Record<string, { label: string; color: string; bg: string }> = {
  confirmed: { label: "확정", color: "#778C86", bg: "rgba(119,140,134,0.12)" },
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

export default function ProblemsPage() {
  return (
    <Box>
      <Box sx={{ mb: 4 }}>
        <Typography variant="h4" sx={{ fontWeight: 700, color: "#FFFFFF" }}>
          문제 라이브러리
        </Typography>
        <Typography variant="body2" sx={{ color: "#919497", mt: 0.5 }}>
          추출된 수학 문제를 검색하고 관리합니다
        </Typography>
      </Box>

      {/* Filters */}
      <Box sx={{ mb: 3, display: "flex", gap: 1.5, alignItems: "center" }}>
        <TextField
          size="small"
          placeholder="문제 내용 검색..."
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
        <FormControl size="small">
          <Select defaultValue="all" sx={selectSx}>
            <MenuItem value="all">전체 난이도</MenuItem>
            <MenuItem value="easy">쉬움</MenuItem>
            <MenuItem value="medium">보통</MenuItem>
            <MenuItem value="hard">어려움</MenuItem>
          </Select>
        </FormControl>
        <FormControl size="small">
          <Select defaultValue="all" sx={selectSx}>
            <MenuItem value="all">전체 상태</MenuItem>
            <MenuItem value="confirmed">확정</MenuItem>
            <MenuItem value="pending">검수대기</MenuItem>
            <MenuItem value="rejected">반려</MenuItem>
          </Select>
        </FormControl>
      </Box>

      {/* Problems Table */}
      <Card>
        <CardContent sx={{ p: 0 }}>
          <TableContainer>
            <Table>
              <TableHead>
                <TableRow>
                  <TableCell sx={{ width: 50 }}>#</TableCell>
                  <TableCell>문제 내용</TableCell>
                  <TableCell>난이도</TableCell>
                  <TableCell>태그</TableCell>
                  <TableCell>출처</TableCell>
                  <TableCell>상태</TableCell>
                  <TableCell align="right" />
                </TableRow>
              </TableHead>
              <TableBody>
                {mockProblems.map((prob) => {
                  const diff = difficultyConfig[prob.difficulty];
                  const st = statusLabels[prob.status];
                  return (
                    <TableRow
                      key={prob.id}
                      sx={{
                        "&:hover": {
                          backgroundColor: "rgba(255,255,255,0.02)",
                        },
                      }}
                    >
                      <TableCell>
                        <Typography
                          variant="body2"
                          sx={{ color: "#919497", fontSize: 13 }}
                        >
                          {prob.questionNumber}
                        </Typography>
                      </TableCell>
                      <TableCell sx={{ maxWidth: 360 }}>
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
                          {prob.content}
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
                          {prob.tags.map((tag) => (
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
                          ))}
                        </Box>
                      </TableCell>
                      <TableCell>
                        <Typography
                          variant="body2"
                          sx={{ color: "#919497", fontSize: 12 }}
                        >
                          {prob.source}
                        </Typography>
                      </TableCell>
                      <TableCell>
                        <Chip
                          label={st.label}
                          size="small"
                          sx={{
                            color: st.color,
                            backgroundColor: st.bg,
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
              </TableBody>
            </Table>
          </TableContainer>
        </CardContent>
      </Card>
    </Box>
  );
}
