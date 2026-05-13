import { TextField } from "@mui/material";

export function MarkdownField({
  label,
  value,
  minRows = 5,
  onChange,
}: {
  label: string;
  value: string;
  minRows?: number;
  onChange: (value: string) => void;
}) {
  return (
    <TextField
      label={label}
      value={value}
      onChange={(event) => onChange(event.target.value)}
      fullWidth
      multiline
      minRows={minRows}
    />
  );
}
