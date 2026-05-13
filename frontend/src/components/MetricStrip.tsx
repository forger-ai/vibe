import { Paper, Stack, Typography } from "@mui/material";

export function MetricStrip({
  items,
}: {
  items: Array<{ label: string; value: string | number }>;
}) {
  return (
    <Stack direction={{ xs: "column", md: "row" }} spacing={1.25} sx={{ mb: 2 }}>
      {items.map((item) => (
        <Paper key={item.label} sx={{ p: 1.5, flex: 1, borderRadius: 1 }}>
          <Typography variant="caption" color="text.secondary">
            {item.label}
          </Typography>
          <Typography variant="h5" fontWeight={850}>
            {item.value}
          </Typography>
        </Paper>
      ))}
    </Stack>
  );
}
