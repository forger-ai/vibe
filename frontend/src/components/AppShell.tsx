import type { ReactNode } from "react";
import {
  AccountTree,
  Chat,
  DataObject,
  Hub,
  Psychology,
  RocketLaunch,
  Terminal,
  Settings,
  Source,
  Tune,
} from "@mui/icons-material";
import {
  AppBar,
  Box,
  Chip,
  Drawer,
  List,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  Stack,
  Toolbar,
  Typography,
} from "@mui/material";
import type { Plan } from "../api/types";
import { statusColor } from "../lib/status";

export type ViewMode =
  | "feature-intake"
  | "free-chat"
  | "repositories"
  | "databases"
  | "agents"
  | "plans"
  | "step-types"
  | "scripts"
  | "settings";

const drawerWidth = 250;
const appBarHeight = 64;

const navItems: Array<{ view: ViewMode; label: string; icon: ReactNode }> = [
  { view: "feature-intake", label: "Feature Intake", icon: <RocketLaunch /> },
  { view: "free-chat", label: "Free Chat", icon: <Chat /> },
  { view: "repositories", label: "Repositories", icon: <Source /> },
  { view: "databases", label: "Databases", icon: <DataObject /> },
  { view: "agents", label: "Agents", icon: <Psychology /> },
  { view: "plans", label: "Plans", icon: <AccountTree /> },
  { view: "step-types", label: "Step Types", icon: <Tune /> },
  { view: "scripts", label: "Scripts", icon: <Terminal /> },
];

const activePlanStatusLabel = (status: string) => {
  if (status === "awaiting_review") return "awaiting review";
  return status.replace(/_/g, " ");
};

export function AppShell({
  children,
  viewMode,
  activePlans,
  onViewChange,
  onPlanSelect,
}: {
  children: ReactNode;
  viewMode: ViewMode;
  activePlans: Plan[];
  onViewChange: (view: ViewMode) => void;
  onPlanSelect: (plan: Plan) => void;
}) {
  return (
    <Box sx={{ display: "flex", minHeight: "100vh", bgcolor: "background.default" }}>
      <AppBar
        color="inherit"
        elevation={0}
        position="fixed"
        sx={{
          zIndex: (theme) => theme.zIndex.drawer + 1,
          borderBottom: "1px solid",
          borderColor: "divider",
          bgcolor: "rgba(13, 15, 18, 0.88)",
          backdropFilter: "blur(16px)",
        }}
      >
        <Toolbar sx={{ minHeight: `${appBarHeight}px !important`, px: 3 }}>
          <Stack direction="row" spacing={1.25} alignItems="center">
            <Hub color="primary" />
            <Box>
              <Typography sx={{ fontSize: 22, fontWeight: 850, letterSpacing: 0 }}>
                Vibe
              </Typography>
              <Typography variant="caption" color="text.secondary">
                local coding agents
              </Typography>
            </Box>
          </Stack>
        </Toolbar>
      </AppBar>

      <Drawer
        open
        variant="permanent"
        sx={{
          width: drawerWidth,
          flexShrink: 0,
          display: { xs: "none", md: "block" },
          "& .MuiDrawer-paper": {
            width: drawerWidth,
            boxSizing: "border-box",
            pt: `${appBarHeight}px`,
            borderTop: 0,
          },
        }}
      >
        <Stack sx={{ height: "100%" }}>
          <List sx={{ px: 1.5, py: 1.5 }}>
            {navItems.map((item) => (
              <ListItemButton
                key={item.view}
                selected={viewMode === item.view}
                sx={{ borderRadius: 1, mt: 0.5 }}
                onClick={() => onViewChange(item.view)}
              >
                <ListItemIcon sx={{ minWidth: 38 }}>{item.icon}</ListItemIcon>
                <ListItemText primary={item.label} />
              </ListItemButton>
            ))}
          </List>

          <Box sx={{ px: 1.5, py: 1 }}>
            <Typography variant="overline" color="text.secondary">
              Active plans
            </Typography>
            <Stack spacing={1} sx={{ mt: 1 }}>
              {activePlans.slice(0, 4).map((plan) => (
                <Box
                  key={plan.id}
                  onClick={() => onPlanSelect(plan)}
                  sx={{
                    p: 1,
                    border: "1px solid",
                    borderColor: "divider",
                    borderRadius: 1,
                    cursor: "pointer",
                    bgcolor: "background.paper",
                  }}
                >
                  <Typography variant="body2" fontWeight={750} noWrap>
                    {plan.name}
                  </Typography>
                  <Chip
                    size="small"
                    label={activePlanStatusLabel(plan.status)}
                    color={statusColor(plan.status)}
                    sx={{ mt: 0.75, maxWidth: "100%" }}
                  />
                </Box>
              ))}
              {activePlans.length === 0 && (
                <Typography variant="body2" color="text.secondary">
                  No active plans yet.
                </Typography>
              )}
            </Stack>
          </Box>

          <Box sx={{ flexGrow: 1 }} />
          <List sx={{ px: 1.5, pb: 1.5 }}>
            <ListItemButton
              selected={viewMode === "settings"}
              sx={{ borderRadius: 1 }}
              onClick={() => onViewChange("settings")}
            >
              <ListItemIcon sx={{ minWidth: 38 }}>
                <Settings />
              </ListItemIcon>
              <ListItemText primary="Settings" />
            </ListItemButton>
          </List>
        </Stack>
      </Drawer>

      <Box component="main" sx={{ flexGrow: 1, width: { xs: "100%", md: `calc(100% - ${drawerWidth}px)` }, minWidth: 0 }}>
        <Toolbar sx={{ minHeight: `${appBarHeight}px !important` }} />
        <Box sx={{ px: { xs: 1.5, md: 2.5 }, py: 2, minWidth: 0 }}>{children}</Box>
      </Box>
    </Box>
  );
}
