"use client";

import { Box } from "@mui/material";
import { MathJax } from "better-react-mathjax";

function createImageRegexes() {
  return {
    markdown: /!\[[^\]]*]\((https?:\/\/[^\s)]+)\)/gi,
    html: /<img\b[^>]*\bsrc=["'](https?:\/\/[^"']+)["'][^>]*>/gi,
    includeGraphics: /\\includegraphics(?:\[[^\]]*\])?\{(https?:\/\/[^}]+)\}/gi,
  };
}

export interface ProblemStatementAssetViewItem {
  id?: string | number | null;
  asset_type?: string | null;
  preview_url?: string | null;
  storage_key?: string | null;
}

interface ProblemStatementViewProps {
  text: string | null | undefined;
  assets?: ProblemStatementAssetViewItem[];
}

function normalizeMathOperators(text: string): string {
  // Force TeX operator limits placement for inline \lim_{} cases from OCR.
  return text.replace(/\\lim\s*_/g, "\\lim\\limits_");
}

function dedupeStrings(values: string[]): string[] {
  const seen = new Set<string>();
  const deduped: string[] = [];
  for (const value of values) {
    const normalized = value.trim();
    if (!normalized || seen.has(normalized)) {
      continue;
    }
    seen.add(normalized);
    deduped.push(normalized);
  }
  return deduped;
}

function extractInlineImageUrls(text: string): string[] {
  const regexes = createImageRegexes();
  const urls = [
    ...Array.from(text.matchAll(regexes.markdown), (match) => match[1] || ""),
    ...Array.from(text.matchAll(regexes.html), (match) => match[1] || ""),
    ...Array.from(text.matchAll(regexes.includeGraphics), (match) => match[1] || ""),
  ];
  return dedupeStrings(urls);
}

function stripInlineImageSyntax(text: string): string {
  const regexes = createImageRegexes();
  return text
    .replace(regexes.markdown, "")
    .replace(regexes.html, "")
    .replace(regexes.includeGraphics, "")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function isGraphArtifactLine(line: string): boolean {
  const normalized = line.trim().replace(/\s+/g, "").replace(/−/g, "-");
  if (!normalized) {
    return false;
  }
  if (/^[+-]?\d+(?:\.\d+)?$/.test(normalized)) {
    return true;
  }
  if (/^[xyo]$/i.test(normalized)) {
    return true;
  }
  if (/^(x축|y축)$/i.test(normalized)) {
    return true;
  }
  if (/^(y=f\(x\)|f\(x\))$/i.test(normalized)) {
    return true;
  }
  return false;
}

function stripGraphArtifactLines(text: string, options: { hasVisualImages: boolean }): string {
  const { hasVisualImages } = options;
  if (!hasVisualImages) {
    return text;
  }

  const lines = text.split(/\r?\n/);
  const artifactCount = lines.filter((line) => isGraphArtifactLine(line)).length;
  if (artifactCount < 4) {
    // Guardrail: only strip when graph-noise signature is strong.
    return text;
  }

  return lines
    .filter((line) => !isGraphArtifactLine(line))
    .join("\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

export function ProblemStatementView({
  text,
  assets = [],
}: ProblemStatementViewProps) {
  const sourceText = typeof text === "string" ? text : "";
  const inlineImageUrls = extractInlineImageUrls(sourceText);
  const assetPreviewUrls = dedupeStrings(
    assets
      .map((asset) => asset.preview_url)
      .filter((url): url is string => typeof url === "string" && url.trim().length > 0),
  );
  const renderImageUrls = dedupeStrings([...inlineImageUrls, ...assetPreviewUrls]);
  const cleanedText = normalizeMathOperators(
    stripGraphArtifactLines(stripInlineImageSyntax(sourceText), {
      hasVisualImages: renderImageUrls.length > 0,
    }),
  );

  return (
    <Box>
      <Box
        sx={{
          color: "#F5F7F8",
          whiteSpace: "pre-wrap",
          fontSize: { xs: 15, md: 17 },
          lineHeight: 1.95,
          letterSpacing: "0.005em",
        }}
      >
        <MathJax dynamic>{cleanedText || "(본문 없음)"}</MathJax>
      </Box>

      {renderImageUrls.length > 0 && (
        <Box sx={{ mt: 2, display: "flex", flexDirection: "column", gap: 1.5 }}>
          {renderImageUrls.map((url, index) => (
            <Box
              key={`inline-visual-${index + 1}`}
              component="img"
              src={url}
              alt={`inline-visual-${index + 1}`}
              sx={{
                display: "block",
                width: "100%",
                maxHeight: { xs: 280, md: 420 },
                objectFit: "contain",
                border: "1px solid rgba(231,227,227,0.12)",
                borderRadius: 1.5,
                backgroundColor: "rgba(255,255,255,0.02)",
              }}
            />
          ))}
        </Box>
      )}
    </Box>
  );
}
