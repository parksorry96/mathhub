import { Box } from "@mui/material";
import Sidebar from "./Sidebar";
import TopBar from "./TopBar";

export default function AppShell({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <Box
      sx={{
        minHeight: "100vh",
        backgroundColor: "#0B0B0B",
        display: "flex",
      }}
    >
      <Sidebar />
      <Box
        sx={{
          flex: 1,
          minWidth: 0,
          minHeight: "100vh",
        }}
      >
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
