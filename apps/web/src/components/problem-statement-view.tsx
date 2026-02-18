"use client";

import { Box, Typography } from "@mui/material";
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

export function ProblemStatementView({
  text,
  assets = [],
}: ProblemStatementViewProps) {
  const sourceText = typeof text === "string" ? text : "";
  const inlineImageUrls = extractInlineImageUrls(sourceText);
  const cleanedText = normalizeMathOperators(stripInlineImageSyntax(sourceText));

  const mappedAssets = assets.map((asset, index) => ({
    id: asset.id ?? `asset-${index + 1}`,
    assetType: String(asset.asset_type || "image"),
    previewUrl: asset.preview_url || null,
    storageKey: asset.storage_key || null,
    source: "asset" as const,
  }));

  const previewUrlSet = new Set(
    mappedAssets
      .map((asset) => asset.previewUrl)
      .filter((url): url is string => typeof url === "string" && url.length > 0),
  );
  const inlineAssets = inlineImageUrls
    .filter((url) => !previewUrlSet.has(url))
    .map((url, index) => ({
      id: `inline-${index + 1}`,
      assetType: "image",
      previewUrl: url,
      storageKey: null,
      source: "inline" as const,
    }));

  const renderAssets = [...mappedAssets, ...inlineAssets];

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

      {renderAssets.length > 0 && (
        <Box sx={{ mt: 2 }}>
          <Typography variant="caption" sx={{ color: "#9CB3C8", fontWeight: 600 }}>
            문항 시각 요소 ({renderAssets.length})
          </Typography>
          <Box
            sx={{
              mt: 1,
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))",
              gap: 1,
            }}
          >
            {renderAssets.map((asset) => (
              <Box
                key={String(asset.id)}
                sx={{
                  border: "1px solid rgba(231,227,227,0.12)",
                  borderRadius: 1.5,
                  overflow: "hidden",
                  backgroundColor: "rgba(255,255,255,0.03)",
                }}
              >
                {asset.previewUrl ? (
                  <Box
                    component="img"
                    src={asset.previewUrl}
                    alt={`${asset.assetType}-${asset.id}`}
                    sx={{ width: "100%", height: 96, objectFit: "cover", display: "block" }}
                  />
                ) : (
                  <Box
                    sx={{
                      width: "100%",
                      height: 96,
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      color: "#7F8A93",
                      fontSize: 12,
                    }}
                  >
                    미리보기 불가
                  </Box>
                )}
                <Box sx={{ p: 0.75, display: "flex", justifyContent: "space-between", gap: 1 }}>
                  <Typography variant="caption" sx={{ color: "#D4A574" }}>
                    {asset.assetType}
                  </Typography>
                  {asset.source === "inline" && (
                    <Typography variant="caption" sx={{ color: "#7FA6C8" }}>
                      inline
                    </Typography>
                  )}
                </Box>
              </Box>
            ))}
          </Box>
        </Box>
      )}
    </Box>
  );
}
