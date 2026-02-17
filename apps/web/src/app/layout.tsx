import type { Metadata } from "next";
import ThemeRegistry from "@/theme/ThemeRegistry";
import AppShell from "@/components/layout/AppShell";

export const metadata: Metadata = {
  title: "MathHub — 수학 문제 관리 플랫폼",
  description:
    "Math OCR → 문제 DB → 교재/평가 플랫폼. PDF를 업로드하면 수학 문제를 자동으로 추출하고 관리합니다.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ko">
      <head>
        <link
          rel="stylesheet"
          as="style"
          crossOrigin="anonymous"
          href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css"
        />
      </head>
      <body style={{ margin: 0 }}>
        <ThemeRegistry>
          <AppShell>{children}</AppShell>
        </ThemeRegistry>
      </body>
    </html>
  );
}
