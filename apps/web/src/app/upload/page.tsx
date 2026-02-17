"use client";

import { useState, useCallback } from "react";
import {
  Box,
  Card,
  CardContent,
  Typography,
  Button,
  LinearProgress,
  IconButton,
  Chip,
} from "@mui/material";
import CloudUploadRoundedIcon from "@mui/icons-material/CloudUploadRounded";
import InsertDriveFileRoundedIcon from "@mui/icons-material/InsertDriveFileRounded";
import CloseRoundedIcon from "@mui/icons-material/CloseRounded";
import CheckCircleRoundedIcon from "@mui/icons-material/CheckCircleRounded";

interface UploadFile {
  name: string;
  size: string;
  progress: number;
  status: "uploading" | "done" | "error";
}

const demoFiles: UploadFile[] = [
  { name: "중3_1학기_중간고사.pdf", size: "4.2 MB", progress: 100, status: "done" },
  { name: "고1_수학(상)_단원평가.pdf", size: "2.8 MB", progress: 62, status: "uploading" },
];

export default function UploadPage() {
  const [files] = useState<UploadFile[]>(demoFiles);
  const [isDragOver, setIsDragOver] = useState(false);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(true);
  }, []);

  const handleDragLeave = useCallback(() => {
    setIsDragOver(false);
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(false);
  }, []);

  return (
    <Box>
      <Box sx={{ mb: 4 }}>
        <Typography variant="h4" sx={{ fontWeight: 700, color: "#FFFFFF" }}>
          PDF 업로드
        </Typography>
        <Typography variant="body2" sx={{ color: "#919497", mt: 0.5 }}>
          수학 교재 PDF를 업로드하여 문제를 자동으로 추출합니다
        </Typography>
      </Box>

      {/* Upload Zone */}
      <Card sx={{ mb: 3 }}>
        <CardContent sx={{ p: 0 }}>
          <Box
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
            sx={{
              p: 8,
              textAlign: "center",
              border: "2px dashed",
              borderColor: isDragOver
                ? "rgba(231,227,227,0.3)"
                : "rgba(231,227,227,0.1)",
              borderRadius: 3,
              m: 3,
              cursor: "pointer",
              transition: "all 0.2s ease",
              backgroundColor: isDragOver
                ? "rgba(255,255,255,0.03)"
                : "transparent",
            }}
          >
            <CloudUploadRoundedIcon
              sx={{ fontSize: 56, color: "#919497", mb: 2 }}
            />
            <Typography
              variant="h6"
              sx={{ color: "#E7E3E3", fontWeight: 600, mb: 1 }}
            >
              파일을 드래그하여 업로드
            </Typography>
            <Typography variant="body2" sx={{ color: "#919497", mb: 3 }}>
              또는 클릭하여 파일을 선택하세요
            </Typography>
            <Button
              variant="outlined"
              sx={{
                borderColor: "#E7E3E3",
                color: "#E7E3E3",
                "&:hover": {
                  borderColor: "#FFFFFF",
                  backgroundColor: "rgba(255,255,255,0.04)",
                },
              }}
            >
              파일 선택
            </Button>
            <Typography
              variant="caption"
              sx={{ color: "#52525B", display: "block", mt: 2 }}
            >
              PDF 형식 · 최대 50MB · 복수 파일 동시 업로드 가능
            </Typography>
          </Box>
        </CardContent>
      </Card>

      {/* File List */}
      <Card>
        <CardContent sx={{ p: 0 }}>
          <Box
            sx={{
              px: 3,
              py: 2,
              borderBottom: "1px solid rgba(231,227,227,0.06)",
            }}
          >
            <Typography
              variant="subtitle2"
              sx={{ fontWeight: 600, color: "#FFFFFF" }}
            >
              업로드 파일 ({files.length})
            </Typography>
          </Box>
          {files.map((file, i) => (
            <Box
              key={i}
              sx={{
                px: 3,
                py: 2,
                display: "flex",
                alignItems: "center",
                gap: 2,
                borderBottom:
                  i < files.length - 1
                    ? "1px solid rgba(231,227,227,0.04)"
                    : "none",
              }}
            >
              <InsertDriveFileRoundedIcon
                sx={{ fontSize: 20, color: "#919497" }}
              />
              <Box sx={{ flex: 1 }}>
                <Box
                  sx={{
                    display: "flex",
                    justifyContent: "space-between",
                    mb: 0.5,
                  }}
                >
                  <Typography
                    variant="body2"
                    sx={{ color: "#FFFFFF", fontWeight: 500, fontSize: 13 }}
                  >
                    {file.name}
                  </Typography>
                  <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
                    <Typography variant="caption" sx={{ color: "#919497" }}>
                      {file.size}
                    </Typography>
                    {file.status === "done" ? (
                      <Chip
                        icon={
                          <CheckCircleRoundedIcon sx={{ fontSize: "14px !important" }} />
                        }
                        label="완료"
                        size="small"
                        sx={{
                          color: "#778C86",
                          backgroundColor: "rgba(119,140,134,0.12)",
                          fontWeight: 500,
                          fontSize: 11,
                          height: 22,
                          "& .MuiChip-icon": { color: "#778C86" },
                        }}
                      />
                    ) : (
                      <Typography variant="caption" sx={{ color: "#E7E3E3" }}>
                        {file.progress}%
                      </Typography>
                    )}
                  </Box>
                </Box>
                {file.status === "uploading" && (
                  <LinearProgress
                    variant="determinate"
                    value={file.progress}
                    sx={{
                      "& .MuiLinearProgress-bar": {
                        backgroundColor: "#E7E3E3",
                      },
                    }}
                  />
                )}
              </Box>
              <IconButton size="small" sx={{ color: "#52525B" }}>
                <CloseRoundedIcon sx={{ fontSize: 16 }} />
              </IconButton>
            </Box>
          ))}
        </CardContent>
      </Card>
    </Box>
  );
}
