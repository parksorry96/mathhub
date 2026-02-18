"use client";

import { useCallback, useRef, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  IconButton,
  LinearProgress,
  Typography,
} from "@mui/material";
import CloudUploadRoundedIcon from "@mui/icons-material/CloudUploadRounded";
import InsertDriveFileRoundedIcon from "@mui/icons-material/InsertDriveFileRounded";
import CloseRoundedIcon from "@mui/icons-material/CloseRounded";
import CheckCircleRoundedIcon from "@mui/icons-material/CheckCircleRounded";
import { createOcrJob, presignS3Upload, uploadFileToS3PresignedUrl } from "@/lib/api";

interface UploadFile {
  id: string;
  name: string;
  sizeLabel: string;
  progress: number;
  status: "uploading" | "done" | "error";
  jobId?: string;
  errorMessage?: string;
}

function formatBytes(bytes: number) {
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const exp = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / 1024 ** exp).toFixed(exp === 0 ? 0 : 1)} ${units[exp]}`;
}

async function sha256Hex(file: File) {
  const buffer = await file.arrayBuffer();
  const digest = await crypto.subtle.digest("SHA-256", buffer);
  return Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

export default function UploadPage() {
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [files, setFiles] = useState<UploadFile[]>([]);
  const [isDragOver, setIsDragOver] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const updateFile = useCallback((id: string, patch: Partial<UploadFile>) => {
    setFiles((prev) => prev.map((file) => (file.id === id ? { ...file, ...patch } : file)));
  }, []);

  const processFiles = useCallback(
    async (incoming: File[]) => {
      setError(null);
      setNotice(null);

      for (const file of incoming) {
        const id = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
        const initial: UploadFile = {
          id,
          name: file.name,
          sizeLabel: formatBytes(file.size),
          progress: 10,
          status: "uploading",
        };
        setFiles((prev) => [initial, ...prev]);

        if (!file.name.toLowerCase().endsWith(".pdf")) {
          updateFile(id, {
            status: "error",
            progress: 100,
            errorMessage: "PDF 파일만 업로드할 수 있습니다.",
          });
          continue;
        }

        try {
          const hash = await sha256Hex(file);
          updateFile(id, { progress: 30 });

          const presigned = await presignS3Upload({
            filename: file.name,
            content_type: file.type || "application/pdf",
            prefix: "ocr",
            expires_in_sec: 900,
          });
          updateFile(id, { progress: 55 });

          await uploadFileToS3PresignedUrl({
            uploadUrl: presigned.upload_url,
            file,
            headers: presigned.upload_headers,
          });
          updateFile(id, { progress: 85 });

          const payload = {
            storage_key: presigned.storage_key,
            original_filename: file.name,
            mime_type: file.type || "application/pdf",
            file_size_bytes: file.size,
            sha256: hash,
            provider: "mathpix",
          };
          const created = await createOcrJob(payload);
          updateFile(id, {
            status: "done",
            progress: 100,
            jobId: created.id,
          });
          setNotice(
            "S3 업로드 및 작업 등록이 완료되었습니다. 작업 목록에서 Mathpix 제출/동기화를 실행하세요.",
          );
        } catch (err) {
          updateFile(id, {
            status: "error",
            progress: 100,
            errorMessage: err instanceof Error ? err.message : "업로드 처리 실패",
          });
          setError(err instanceof Error ? err.message : "업로드 처리 실패");
        }
      }
    },
    [updateFile],
  );

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(true);
  }, []);

  const handleDragLeave = useCallback(() => {
    setIsDragOver(false);
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragOver(false);
      const incoming = Array.from(e.dataTransfer.files ?? []);
      void processFiles(incoming);
    },
    [processFiles],
  );

  const handleSelectClick = useCallback(() => {
    fileInputRef.current?.click();
  }, []);

  const handleInputChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const incoming = Array.from(e.target.files ?? []);
      void processFiles(incoming);
      e.target.value = "";
    },
    [processFiles],
  );

  const removeFile = useCallback((id: string) => {
    setFiles((prev) => prev.filter((file) => file.id !== id));
  }, []);

  return (
    <Box>
      <Box sx={{ mb: 4 }}>
        <Typography variant="h4" sx={{ fontWeight: 700, color: "#FFFFFF" }}>
          PDF 업로드
        </Typography>
        <Typography variant="body2" sx={{ color: "#919497", mt: 0.5 }}>
          S3 presigned URL로 PDF 업로드 후 OCR 작업을 등록합니다
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
              borderColor: isDragOver ? "rgba(231,227,227,0.3)" : "rgba(231,227,227,0.1)",
              borderRadius: 3,
              m: 3,
              cursor: "pointer",
              transition: "all 0.2s ease",
              backgroundColor: isDragOver ? "rgba(255,255,255,0.03)" : "transparent",
            }}
            onClick={handleSelectClick}
          >
            <CloudUploadRoundedIcon sx={{ fontSize: 56, color: "#919497", mb: 2 }} />
            <Typography variant="h6" sx={{ color: "#E7E3E3", fontWeight: 600, mb: 1 }}>
              파일을 드래그하여 등록
            </Typography>
            <Typography variant="body2" sx={{ color: "#919497", mb: 3 }}>
              또는 클릭하여 PDF 파일을 선택하세요
            </Typography>
            <Button
              variant="outlined"
              onClick={handleSelectClick}
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
            <Typography variant="caption" sx={{ color: "#52525B", display: "block", mt: 2 }}>
              PDF 형식 · S3 업로드 + SHA-256 계산 + API 등록
            </Typography>
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf,application/pdf"
              multiple
              hidden
              onChange={handleInputChange}
            />
          </Box>
        </CardContent>
      </Card>

      <Card>
        <CardContent sx={{ p: 0 }}>
          <Box sx={{ px: 3, py: 2, borderBottom: "1px solid rgba(231,227,227,0.06)" }}>
            <Typography variant="subtitle2" sx={{ fontWeight: 600, color: "#FFFFFF" }}>
              등록 파일 ({files.length})
            </Typography>
          </Box>
          {files.map((file, i) => (
            <Box
              key={file.id}
              sx={{
                px: 3,
                py: 2,
                display: "flex",
                alignItems: "center",
                gap: 2,
                borderBottom: i < files.length - 1 ? "1px solid rgba(231,227,227,0.04)" : "none",
              }}
            >
              <InsertDriveFileRoundedIcon sx={{ fontSize: 20, color: "#919497" }} />
              <Box sx={{ flex: 1 }}>
                <Box sx={{ display: "flex", justifyContent: "space-between", mb: 0.5 }}>
                  <Typography variant="body2" sx={{ color: "#FFFFFF", fontWeight: 500, fontSize: 13 }}>
                    {file.name}
                  </Typography>
                  <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
                    <Typography variant="caption" sx={{ color: "#919497" }}>
                      {file.sizeLabel}
                    </Typography>
                    {file.status === "done" ? (
                      <Chip
                        icon={<CheckCircleRoundedIcon sx={{ fontSize: "14px !important" }} />}
                        label="등록 완료"
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
                    ) : file.status === "error" ? (
                      <Chip
                        label="실패"
                        size="small"
                        sx={{
                          color: "#C45C5C",
                          backgroundColor: "rgba(196,92,92,0.12)",
                          fontWeight: 500,
                          fontSize: 11,
                          height: 22,
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
                    sx={{ "& .MuiLinearProgress-bar": { backgroundColor: "#E7E3E3" } }}
                  />
                )}
                {file.status === "done" && file.jobId && (
                  <Typography variant="caption" sx={{ color: "#52525B" }}>
                    job_id: {file.jobId}
                  </Typography>
                )}
                {file.status === "error" && file.errorMessage && (
                  <Typography variant="caption" sx={{ color: "#C45C5C" }}>
                    {file.errorMessage}
                  </Typography>
                )}
              </Box>
              <IconButton size="small" sx={{ color: "#52525B" }} onClick={() => removeFile(file.id)}>
                <CloseRoundedIcon sx={{ fontSize: 16 }} />
              </IconButton>
            </Box>
          ))}
          {files.length === 0 && (
            <Box sx={{ px: 3, py: 4 }}>
              <Typography variant="body2" sx={{ color: "#919497" }}>
                아직 등록된 파일이 없습니다.
              </Typography>
            </Box>
          )}
        </CardContent>
      </Card>
    </Box>
  );
}
