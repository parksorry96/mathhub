"use client";

import { createTheme } from "@mui/material/styles";

const theme = createTheme({
  palette: {
    mode: "dark",
    primary: {
      main: "#262A2D",
      light: "#3a3f43",
      dark: "#1a1d1f",
      contrastText: "#FFFFFF",
    },
    secondary: {
      main: "#919497",
      light: "#a8aaad",
      dark: "#6b6d70",
      contrastText: "#FFFFFF",
    },
    background: {
      default: "#0B0B0B",
      paper: "#141414",
    },
    text: {
      primary: "#FFFFFF",
      secondary: "#919497",
      disabled: "#52525B",
    },
    divider: "#E7E3E3",
    error: {
      main: "#C45C5C",
    },
    success: {
      main: "#778C86",
    },
    info: {
      main: "#919497",
    },
    warning: {
      main: "#D4A574",
    },
  },
  typography: {
    fontFamily: "'Pretendard Variable', Pretendard, -apple-system, BlinkMacSystemFont, system-ui, Roboto, sans-serif",
    h1: { fontWeight: 700, letterSpacing: "-0.02em" },
    h2: { fontWeight: 700, letterSpacing: "-0.02em" },
    h3: { fontWeight: 600, letterSpacing: "-0.01em" },
    h4: { fontWeight: 600 },
    h5: { fontWeight: 600 },
    h6: { fontWeight: 600 },
    subtitle1: { color: "#919497" },
    subtitle2: { color: "#919497" },
    body2: { color: "#919497" },
  },
  shape: {
    borderRadius: 12,
  },
  components: {
    MuiButton: {
      styleOverrides: {
        root: {
          textTransform: "none",
          fontWeight: 600,
          borderRadius: 8,
          padding: "8px 20px",
        },
        contained: {
          backgroundColor: "#262A2D",
          color: "#FFFFFF",
          "&:hover": {
            backgroundColor: "#3a3f43",
          },
        },
        outlined: {
          borderColor: "#E7E3E3",
          color: "#E7E3E3",
          "&:hover": {
            borderColor: "#FFFFFF",
            backgroundColor: "rgba(255,255,255,0.04)",
          },
        },
      },
    },
    MuiCard: {
      styleOverrides: {
        root: {
          backgroundColor: "#141414",
          border: "1px solid rgba(231,227,227,0.08)",
          borderRadius: 16,
          backgroundImage: "none",
        },
      },
    },
    MuiChip: {
      styleOverrides: {
        root: {
          fontWeight: 500,
          borderRadius: 6,
        },
      },
    },
    MuiTableCell: {
      styleOverrides: {
        root: {
          borderColor: "rgba(231,227,227,0.08)",
        },
        head: {
          color: "#919497",
          fontWeight: 600,
          fontSize: "0.75rem",
          textTransform: "uppercase",
          letterSpacing: "0.05em",
        },
      },
    },
    MuiPaper: {
      styleOverrides: {
        root: {
          backgroundImage: "none",
        },
      },
    },
    MuiLinearProgress: {
      styleOverrides: {
        root: {
          borderRadius: 4,
          backgroundColor: "rgba(231,227,227,0.08)",
        },
        bar: {
          borderRadius: 4,
        },
      },
    },
  },
});

export default theme;
