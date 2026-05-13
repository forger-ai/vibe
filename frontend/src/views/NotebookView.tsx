import { useState } from "react";
import { Add } from "@mui/icons-material";
import { Button, Paper, Stack, TextField, Typography } from "@mui/material";
import type { NotebookEntry } from "../api/types";
import { api } from "../api/vibe";
import { MarkdownField } from "../components/MarkdownField";
import { SectionHeader } from "../components/SectionHeader";

export function NotebookView({
  entries,
  onChanged,
}: {
  entries: NotebookEntry[];
  onChanged: () => void;
}) {
  const [title, setTitle] = useState("");
  const [shortDescription, setShortDescription] = useState("");
  const [content, setContent] = useState("");

  async function create() {
    await api.createNotebook({
      title,
      short_description: shortDescription,
      long_description_md: content,
      entry_type: "log",
      load_policy: "retrieval",
    });
    setTitle("");
    setShortDescription("");
    setContent("");
    await onChanged();
  }

  return (
    <Stack spacing={2}>
      <SectionHeader title="Settings" subtitle="Notebook entries and app-level configuration for Vibe." />
      <Paper sx={{ p: 2, borderRadius: 1 }}>
        <Stack spacing={1.25}>
          <Typography fontWeight={850}>New notebook entry</Typography>
          <Stack direction={{ xs: "column", md: "row" }} spacing={1}>
            <TextField label="Title" value={title} onChange={(event) => setTitle(event.target.value)} />
            <TextField
              label="Short description"
              value={shortDescription}
              fullWidth
              onChange={(event) => setShortDescription(event.target.value)}
            />
          </Stack>
          <MarkdownField label="Long description" value={content} onChange={setContent} />
          <Button startIcon={<Add />} disabled={!title.trim()} onClick={() => void create()}>
            Add notebook entry
          </Button>
        </Stack>
      </Paper>
      <Stack spacing={1}>
        {entries.map((entry) => (
          <Paper key={entry.id} sx={{ p: 1.5, borderRadius: 1 }}>
            <Typography fontWeight={850}>{entry.title}</Typography>
            <Typography variant="body2" color="text.secondary">
              {entry.short_description}
            </Typography>
            <Typography sx={{ mt: 1, whiteSpace: "pre-wrap" }}>{entry.long_description_md}</Typography>
          </Paper>
        ))}
      </Stack>
    </Stack>
  );
}
