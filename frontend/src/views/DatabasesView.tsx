import { DataObject } from "@mui/icons-material";
import { Alert, Paper, Stack, Typography } from "@mui/material";
import { SectionHeader } from "../components/SectionHeader";

export function DatabasesView() {
  return (
    <Stack spacing={2}>
      <SectionHeader
        title="Databases"
        subtitle="Registry for local and remote database helpers. Advanced DB Manager tooling is outside V1."
      />
      <Paper sx={{ p: 2, borderRadius: 1 }}>
        <Stack direction="row" spacing={1.5} alignItems="center">
          <DataObject color="primary" />
          <Stack>
            <Typography fontWeight={850}>DB Manager placeholder</Typography>
            <Typography color="text.secondary">
              Vibe models database agents now, but V1 focuses on the coding-agent core.
            </Typography>
          </Stack>
        </Stack>
      </Paper>
      <Alert severity="info">
        Connections are not active yet. Future versions can add local and remote database adapters here without
        changing the plan, agent, or notebook model.
      </Alert>
    </Stack>
  );
}
