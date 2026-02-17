"use client";

import { usePathname, useRouter } from "next/navigation";
import {
  Box,
  List,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  Typography,
} from "@mui/material";
import DashboardRoundedIcon from "@mui/icons-material/DashboardRounded";
import CloudUploadRoundedIcon from "@mui/icons-material/CloudUploadRounded";
import WorkHistoryRoundedIcon from "@mui/icons-material/WorkHistoryRounded";
import AutoStoriesRoundedIcon from "@mui/icons-material/AutoStoriesRounded";
import FactCheckRoundedIcon from "@mui/icons-material/FactCheckRounded";

const SIDEBAR_WIDTH = 240;

const navItems = [
  { label: "대시보드", path: "/", icon: <DashboardRoundedIcon /> },
  { label: "업로드", path: "/upload", icon: <CloudUploadRoundedIcon /> },
  { label: "작업 목록", path: "/jobs", icon: <WorkHistoryRoundedIcon /> },
  { label: "문제 관리", path: "/problems", icon: <AutoStoriesRoundedIcon /> },
  { label: "검수", path: "/review", icon: <FactCheckRoundedIcon /> },
];

export default function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();

  return (
    <Box
      component="nav"
      sx={{
        width: SIDEBAR_WIDTH,
        height: "100vh",
        backgroundColor: "#141414",
        borderRight: "1px solid rgba(231,227,227,0.06)",
        display: "flex",
        flexDirection: "column",
        position: "sticky",
        top: 0,
        flexShrink: 0,
      }}
    >
      {/* Logo */}
      <Box sx={{ px: 3, py: 3, mb: 1 }}>
        <Typography
          variant="h5"
          sx={{
            fontWeight: 800,
            color: "#FFFFFF",
            letterSpacing: "-0.03em",
          }}
        >
          MathHub
        </Typography>
        <Typography
          variant="caption"
          sx={{ color: "#919497", letterSpacing: "0.05em" }}
        >
          PROBLEM MANAGEMENT
        </Typography>
      </Box>

      {/* Navigation */}
      <List sx={{ px: 1.5, flex: 1 }}>
        {navItems.map((item) => {
          const isActive =
            item.path === "/"
              ? pathname === "/"
              : pathname.startsWith(item.path);

          return (
            <ListItemButton
              key={item.path}
              onClick={() => router.push(item.path)}
              sx={{
                borderRadius: 2,
                mb: 0.5,
                px: 2,
                py: 1.2,
                backgroundColor: isActive
                  ? "rgba(255,255,255,0.06)"
                  : "transparent",
                "&:hover": {
                  backgroundColor: "rgba(255,255,255,0.04)",
                },
              }}
            >
              <ListItemIcon
                sx={{
                  minWidth: 36,
                  color: isActive ? "#FFFFFF" : "#919497",
                  "& .MuiSvgIcon-root": { fontSize: 20 },
                }}
              >
                {item.icon}
              </ListItemIcon>
              <ListItemText
                primary={item.label}
                primaryTypographyProps={{
                  fontSize: 14,
                  fontWeight: isActive ? 600 : 400,
                  color: isActive ? "#FFFFFF" : "#919497",
                }}
              />
              {isActive && (
                <Box
                  sx={{
                    width: 3,
                    height: 20,
                    borderRadius: 2,
                    backgroundColor: "#E7E3E3",
                    position: "absolute",
                    right: 0,
                  }}
                />
              )}
            </ListItemButton>
          );
        })}
      </List>

      {/* Footer */}
      <Box sx={{ px: 3, py: 2, borderTop: "1px solid rgba(231,227,227,0.06)" }}>
        <Typography variant="caption" sx={{ color: "#52525B" }}>
          v0.1.0 · MVP
        </Typography>
      </Box>
    </Box>
  );
}

export { SIDEBAR_WIDTH };
