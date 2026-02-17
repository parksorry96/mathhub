"use client";

import {
  Box,
  Card,
  CardContent,
  Typography,
  Chip,
  Button,
  Divider,
} from "@mui/material";
import CheckRoundedIcon from "@mui/icons-material/CheckRounded";
import CloseRoundedIcon from "@mui/icons-material/CloseRounded";
import EditRoundedIcon from "@mui/icons-material/EditRounded";
import NavigateNextRoundedIcon from "@mui/icons-material/NavigateNextRounded";
import NavigateBeforeRoundedIcon from "@mui/icons-material/NavigateBeforeRounded";
import { mockProblems } from "@/mocks/data";

const pendingProblems = mockProblems.filter((p) => p.status === "pending");

export default function ReviewPage() {
  const current = pendingProblems[0];

  return (
    <Box>
      <Box sx={{ mb: 4, display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <Box>
          <Typography variant="h4" sx={{ fontWeight: 700, color: "#FFFFFF" }}>
            검수 큐
          </Typography>
          <Typography variant="body2" sx={{ color: "#919497", mt: 0.5 }}>
            추출된 문제를 확인하고 승인/반려합니다
          </Typography>
        </Box>
        <Chip
          label={`${pendingProblems.length}건 대기`}
          sx={{
            color: "#D4A574",
            backgroundColor: "rgba(212,165,116,0.12)",
            fontWeight: 600,
            fontSize: 13,
          }}
        />
      </Box>

      {current && (
        <Box
          sx={{
            display: "grid",
            gridTemplateColumns: "1fr 320px",
            gap: 2.5,
          }}
        >
          {/* Problem Preview */}
          <Card>
            <CardContent sx={{ p: 3, "&:last-child": { pb: 3 } }}>
              {/* Header */}
              <Box
                sx={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  mb: 3,
                }}
              >
                <Box sx={{ display: "flex", alignItems: "center", gap: 1.5 }}>
                  <Typography
                    variant="caption"
                    sx={{
                      color: "#919497",
                      fontWeight: 600,
                      textTransform: "uppercase",
                      letterSpacing: "0.05em",
                    }}
                  >
                    문항 #{current.questionNumber}
                  </Typography>
                  <Chip
                    label={current.source}
                    size="small"
                    variant="outlined"
                    sx={{
                      borderColor: "rgba(231,227,227,0.1)",
                      color: "#919497",
                      fontSize: 11,
                      height: 20,
                    }}
                  />
                </Box>
                <Box sx={{ display: "flex", gap: 0.5 }}>
                  <Button
                    size="small"
                    startIcon={<NavigateBeforeRoundedIcon />}
                    sx={{ color: "#919497", fontSize: 12, minWidth: "auto" }}
                  >
                    이전
                  </Button>
                  <Button
                    size="small"
                    endIcon={<NavigateNextRoundedIcon />}
                    sx={{ color: "#919497", fontSize: 12, minWidth: "auto" }}
                  >
                    다음
                  </Button>
                </Box>
              </Box>

              {/* Problem Content */}
              <Box
                sx={{
                  backgroundColor: "#1C1C1C",
                  borderRadius: 2,
                  p: 4,
                  mb: 3,
                  minHeight: 200,
                }}
              >
                <Typography
                  variant="body1"
                  sx={{
                    color: "#FFFFFF",
                    fontSize: 16,
                    lineHeight: 1.8,
                    fontWeight: 400,
                  }}
                >
                  {current.content}
                </Typography>
              </Box>

              {/* Actions */}
              <Box sx={{ display: "flex", gap: 1.5, justifyContent: "flex-end" }}>
                <Button
                  variant="outlined"
                  startIcon={<CloseRoundedIcon />}
                  sx={{
                    borderColor: "rgba(196,92,92,0.3)",
                    color: "#C45C5C",
                    "&:hover": {
                      borderColor: "#C45C5C",
                      backgroundColor: "rgba(196,92,92,0.08)",
                    },
                  }}
                >
                  반려
                </Button>
                <Button
                  variant="outlined"
                  startIcon={<EditRoundedIcon />}
                  sx={{
                    borderColor: "rgba(231,227,227,0.12)",
                    color: "#E7E3E3",
                    "&:hover": {
                      borderColor: "#E7E3E3",
                      backgroundColor: "rgba(231,227,227,0.04)",
                    },
                  }}
                >
                  수정
                </Button>
                <Button
                  variant="contained"
                  startIcon={<CheckRoundedIcon />}
                  sx={{
                    backgroundColor: "#262A2D",
                    color: "#FFFFFF",
                    "&:hover": { backgroundColor: "#3a3f43" },
                  }}
                >
                  승인
                </Button>
              </Box>
            </CardContent>
          </Card>

          {/* Side Panel */}
          <Card>
            <CardContent sx={{ p: 3, "&:last-child": { pb: 3 } }}>
              <Typography
                variant="subtitle2"
                sx={{ fontWeight: 600, color: "#FFFFFF", mb: 2 }}
              >
                문항 정보
              </Typography>

              <Box sx={{ display: "flex", flexDirection: "column", gap: 2 }}>
                <Box>
                  <Typography
                    variant="caption"
                    sx={{ color: "#919497", fontWeight: 500 }}
                  >
                    난이도
                  </Typography>
                  <Chip
                    label="보통"
                    size="small"
                    sx={{
                      ml: 1,
                      color: "#E7E3E3",
                      backgroundColor: "rgba(231,227,227,0.08)",
                      fontWeight: 500,
                      fontSize: 11,
                      height: 22,
                    }}
                  />
                </Box>

                <Box>
                  <Typography
                    variant="caption"
                    sx={{
                      color: "#919497",
                      fontWeight: 500,
                      display: "block",
                      mb: 0.5,
                    }}
                  >
                    태그
                  </Typography>
                  <Box sx={{ display: "flex", gap: 0.5, flexWrap: "wrap" }}>
                    {current.tags.map((tag) => (
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
                </Box>

                <Divider sx={{ borderColor: "rgba(231,227,227,0.06)" }} />

                <Box>
                  <Typography
                    variant="caption"
                    sx={{
                      color: "#919497",
                      fontWeight: 500,
                      display: "block",
                      mb: 0.5,
                    }}
                  >
                    출처
                  </Typography>
                  <Typography
                    variant="body2"
                    sx={{ color: "#E7E3E3", fontSize: 13 }}
                  >
                    {current.source}
                  </Typography>
                </Box>

                <Box>
                  <Typography
                    variant="caption"
                    sx={{
                      color: "#919497",
                      fontWeight: 500,
                      display: "block",
                      mb: 0.5,
                    }}
                  >
                    정답
                  </Typography>
                  <Typography
                    variant="body2"
                    sx={{ color: "#52525B", fontSize: 13, fontStyle: "italic" }}
                  >
                    아직 입력되지 않음
                  </Typography>
                </Box>
              </Box>

              <Divider sx={{ borderColor: "rgba(231,227,227,0.06)", my: 2 }} />

              {/* Queue List */}
              <Typography
                variant="caption"
                sx={{
                  color: "#919497",
                  fontWeight: 600,
                  textTransform: "uppercase",
                  letterSpacing: "0.05em",
                  display: "block",
                  mb: 1,
                }}
              >
                대기 목록
              </Typography>
              {pendingProblems.map((p, i) => (
                <Box
                  key={p.id}
                  sx={{
                    py: 1,
                    px: 1.5,
                    borderRadius: 1,
                    backgroundColor:
                      i === 0 ? "rgba(255,255,255,0.04)" : "transparent",
                    cursor: "pointer",
                    "&:hover": { backgroundColor: "rgba(255,255,255,0.03)" },
                    mb: 0.5,
                  }}
                >
                  <Typography
                    variant="body2"
                    sx={{
                      color: i === 0 ? "#FFFFFF" : "#919497",
                      fontSize: 12,
                      fontWeight: i === 0 ? 500 : 400,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                  >
                    #{p.questionNumber} {p.content}
                  </Typography>
                </Box>
              ))}
            </CardContent>
          </Card>
        </Box>
      )}
    </Box>
  );
}
