import { Box } from "@mui/material";
import Sidebar, { SIDEBAR_WIDTH } from "./Sidebar";
import TopBar from "./TopBar";

export default function AppShell({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <Box sx={{ display: "flex", minHeight: "100vh", backgroundColor: "#0B0B0B" }}>
      <Sidebar />
      <Box sx={{ flex: 1, ml: `${SIDEBAR_WIDTH}px` }}>
        <TopBar />
        <Box
          component="main"
          sx={{
            p: 4,
            minHeight: "calc(100vh - 64px)",
          }}
        >
          {children}
        </Box>
      </Box>
    </Box>
  );
}
