import type { ReactNode } from "react";
import { Stack, Typography } from "@mui/material";

export function SectionHeader({
  title,
  subtitle,
  action,
}: {
  title: string;
  subtitle?: string;
  action?: ReactNode;
}) {
  return (
    <Stack direction="row" spacing={2} justifyContent="space-between" alignItems="flex-start" sx={{ mb: 2 }}>
      <Stack spacing={0.4}>
        <Typography variant="h4" fontWeight={850}>
          {title}
        </Typography>
        {subtitle && <Typography color="text.secondary">{subtitle}</Typography>}
      </Stack>
      {action}
    </Stack>
  );
}
