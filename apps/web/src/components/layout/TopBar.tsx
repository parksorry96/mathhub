"use client";

import { Box, InputBase, IconButton, Avatar, Badge } from "@mui/material";
import SearchRoundedIcon from "@mui/icons-material/SearchRounded";
import NotificationsNoneRoundedIcon from "@mui/icons-material/NotificationsNoneRounded";

export default function TopBar() {
  return (
    <Box
      component="header"
      sx={{
        height: 64,
        px: 4,
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        backgroundColor: "#0B0B0B",
        borderBottom: "1px solid rgba(231,227,227,0.06)",
        position: "sticky",
        top: 0,
        zIndex: 1100,
      }}
    >
      {/* Search */}
      <Box
        sx={{
          display: "flex",
          alignItems: "center",
          backgroundColor: "#141414",
          borderRadius: 2,
          px: 2,
          py: 0.5,
          width: 400,
          border: "1px solid rgba(231,227,227,0.06)",
        }}
      >
        <SearchRoundedIcon sx={{ color: "#919497", fontSize: 20, mr: 1 }} />
        <InputBase
          placeholder="문제, 교재, 작업 검색..."
          sx={{
            flex: 1,
            fontSize: 14,
            color: "#FFFFFF",
            "& ::placeholder": { color: "#52525B", opacity: 1 },
          }}
        />
      </Box>

      {/* Right actions */}
      <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
        <IconButton size="small" sx={{ color: "#919497" }}>
          <Badge
            variant="dot"
            sx={{
              "& .MuiBadge-dot": {
                backgroundColor: "#C45C5C",
                width: 6,
                height: 6,
              },
            }}
          >
            <NotificationsNoneRoundedIcon sx={{ fontSize: 22 }} />
          </Badge>
        </IconButton>
        <Avatar
          sx={{
            width: 32,
            height: 32,
            bgcolor: "#262A2D",
            fontSize: 13,
            fontWeight: 600,
            ml: 1,
          }}
        >
          P
        </Avatar>
      </Box>
    </Box>
  );
}
