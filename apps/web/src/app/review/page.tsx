"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  Divider,
  Typography,
} from "@mui/material";
import CheckRoundedIcon from "@mui/icons-material/CheckRounded";
import CloseRoundedIcon from "@mui/icons-material/CloseRounded";
import NavigateNextRoundedIcon from "@mui/icons-material/NavigateNextRounded";
import NavigateBeforeRoundedIcon from "@mui/icons-material/NavigateBeforeRounded";
import { MathJax, MathJaxContext } from "better-react-mathjax";
import { listProblems, reviewProblem, type ProblemListItem } from "@/lib/api";

function difficultyLabel(pointValue: number) {
  if (pointValue <= 2) return "2점";
  if (pointValue === 3) return "3점";
  return "4점";
}

const mathJaxConfig = {
  tex: {
    inlineMath: [["\\(", "\\)"]],
    displayMath: [["\\[", "\\]"]],
  },
};

export default function ReviewPage() {
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [queue, setQueue] = useState<ProblemListItem[]>([]);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [onlyAiReviewed, setOnlyAiReviewed] = useState(true);

  const loadQueue = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await listProblems({
        limit: 100,
        offset: 0,
        review_status: "pending",
        ai_reviewed: onlyAiReviewed ? true : undefined,
      });
      setQueue(res.items);
      setCurrentIndex((prev) => {
        if (res.items.length === 0) return 0;
        return Math.min(prev, res.items.length - 1);
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "검수 큐를 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }, [onlyAiReviewed]);

  useEffect(() => {
    void loadQueue();
  }, [loadQueue]);

  const current = queue[currentIndex];
  const tags = useMemo(() => {
    if (!current) return [] as string[];
    return [current.subject_name_ko, current.unit_name_ko].filter(Boolean) as string[];
  }, [current]);

  const handleReview = useCallback(
    async (action: "approve" | "reject") => {
      if (!current) return;
      setSubmitting(true);
      setError(null);
      setNotice(null);
      try {
        await reviewProblem(current.id, { action });
        setNotice(action === "approve" ? "문항을 승인했습니다." : "문항을 반려했습니다.");
        await loadQueue();
      } catch (err) {
        setError(err instanceof Error ? err.message : "검수 처리에 실패했습니다.");
      } finally {
        setSubmitting(false);
      }
    },
    [current, loadQueue],
  );

  return (
    <Box>
      <Box sx={{ mb: 4, display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <Box>
          <Typography variant="h4" sx={{ fontWeight: 700, color: "#FFFFFF" }}>
            검수 큐
          </Typography>
          <Typography variant="body2" sx={{ color: "#919497", mt: 0.5 }}>
            실제 API(GET /problems, PATCH /problems/{"{id}"}/review) 기반 검수
          </Typography>
          <Box sx={{ mt: 1.25, display: "flex", gap: 0.75 }}>
            <Chip
              label="AI 분류 문항만"
              size="small"
              clickable
              onClick={() => setOnlyAiReviewed((prev) => !prev)}
              variant={onlyAiReviewed ? "filled" : "outlined"}
              sx={{
                color: onlyAiReviewed ? "#7FB3FF" : "#919497",
                backgroundColor: onlyAiReviewed ? "rgba(127,179,255,0.16)" : "transparent",
                borderColor: "rgba(127,179,255,0.35)",
                fontSize: 11,
                height: 22,
              }}
            />
          </Box>
        </Box>
        <Chip
          label={`${queue.length}건 대기`}
          sx={{
            color: "#D4A574",
            backgroundColor: "rgba(212,165,116,0.12)",
            fontWeight: 600,
            fontSize: 13,
          }}
        />
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

      {!loading && !current && (
        <Card>
          <CardContent sx={{ p: 4 }}>
            <Typography variant="body1" sx={{ color: "#E7E3E3" }}>
              현재 검수 대기 문항이 없습니다.
            </Typography>
          </CardContent>
        </Card>
      )}

      {current && (
        <Box sx={{ display: "grid", gridTemplateColumns: "1fr 320px", gap: 2.5 }}>
          <Card>
            <CardContent sx={{ p: 3, "&:last-child": { pb: 3 } }}>
              <Box sx={{ display: "flex", justifyContent: "space-between", alignItems: "center", mb: 3 }}>
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
                    문항 {current.source_problem_label ?? "—"}
                  </Typography>
                  <Chip
                    label={current.source_title ?? current.document_filename ?? "미지정"}
                    size="small"
                    variant="outlined"
                    sx={{
                      borderColor: "rgba(231,227,227,0.1)",
                      color: "#919497",
                      fontSize: 11,
                      height: 20,
                    }}
                    />
                  {current.ai_reviewed && (
                    <Chip
                      label={`AI ${current.ai_provider ?? "heuristic"}`}
                      size="small"
                      sx={{
                        color: "#7FB3FF",
                        backgroundColor: "rgba(127,179,255,0.14)",
                        fontSize: 11,
                        height: 20,
                      }}
                    />
                  )}
                </Box>
                <Box sx={{ display: "flex", gap: 0.5 }}>
                  <Button
                    size="small"
                    startIcon={<NavigateBeforeRoundedIcon />}
                    disabled={currentIndex === 0}
                    onClick={() => setCurrentIndex((prev) => Math.max(0, prev - 1))}
                    sx={{ color: "#919497", fontSize: 12, minWidth: "auto" }}
                  >
                    이전
                  </Button>
                  <Button
                    size="small"
                    endIcon={<NavigateNextRoundedIcon />}
                    disabled={currentIndex >= queue.length - 1}
                    onClick={() => setCurrentIndex((prev) => Math.min(queue.length - 1, prev + 1))}
                    sx={{ color: "#919497", fontSize: 12, minWidth: "auto" }}
                  >
                    다음
                  </Button>
                </Box>
              </Box>

              <Box
                sx={{
                  backgroundColor: "#1C1C1C",
                  borderRadius: 2,
                  p: 4,
                  mb: 3,
                  minHeight: 220,
                }}
              >
                <MathJaxContext config={mathJaxConfig}>
                  <Box sx={{ color: "#FFFFFF", fontSize: 16, lineHeight: 1.8, whiteSpace: "pre-wrap" }}>
                    <MathJax dynamic>{current.content || "(본문 없음)"}</MathJax>
                  </Box>
                </MathJaxContext>
              </Box>

              <Box sx={{ display: "flex", gap: 1.5, justifyContent: "flex-end" }}>
                <Button
                  variant="outlined"
                  startIcon={<CloseRoundedIcon />}
                  onClick={() => void handleReview("reject")}
                  disabled={submitting}
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
                  variant="contained"
                  startIcon={<CheckRoundedIcon />}
                  onClick={() => void handleReview("approve")}
                  disabled={submitting}
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

          <Card>
            <CardContent sx={{ p: 3, "&:last-child": { pb: 3 } }}>
              <Typography variant="subtitle2" sx={{ fontWeight: 600, color: "#FFFFFF", mb: 2 }}>
                문항 정보
              </Typography>

              <Box sx={{ display: "flex", flexDirection: "column", gap: 2 }}>
                <Box>
                  <Typography variant="caption" sx={{ color: "#919497", fontWeight: 500 }}>
                    난이도
                  </Typography>
                  <Chip
                    label={difficultyLabel(current.point_value)}
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
                        태그 없음
                      </Typography>
                    )}
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
                  <Typography variant="body2" sx={{ color: "#E7E3E3", fontSize: 13 }}>
                    {current.source_title ?? current.document_filename ?? "미지정"}
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
                    신뢰도
                  </Typography>
                  <Typography variant="body2" sx={{ color: "#E7E3E3", fontSize: 13 }}>
                    {current.confidence ? `${current.confidence}%` : "정보 없음"}
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
                    AI 분류
                  </Typography>
                  <Typography variant="body2" sx={{ color: "#E7E3E3", fontSize: 13 }}>
                    {current.ai_reviewed
                      ? `${current.ai_provider ?? "heuristic"} / ${current.ai_model ?? "-"}`
                      : "AI 분류 이력 없음"}
                  </Typography>
                </Box>
              </Box>

              <Divider sx={{ borderColor: "rgba(231,227,227,0.06)", my: 2 }} />

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
              {queue.map((item, i) => (
                <Box
                  key={item.id}
                  onClick={() => setCurrentIndex(i)}
                  sx={{
                    py: 1,
                    px: 1.5,
                    borderRadius: 1,
                    backgroundColor: i === currentIndex ? "rgba(255,255,255,0.04)" : "transparent",
                    cursor: "pointer",
                    "&:hover": { backgroundColor: "rgba(255,255,255,0.03)" },
                    mb: 0.5,
                  }}
                >
                  <Typography
                    variant="body2"
                    sx={{
                      color: i === currentIndex ? "#FFFFFF" : "#919497",
                      fontSize: 12,
                      fontWeight: i === currentIndex ? 500 : 400,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {item.source_problem_label ?? "—"} {item.content}
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
