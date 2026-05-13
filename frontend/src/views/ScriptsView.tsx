import { useState } from "react";
import { Add, DeleteOutline } from "@mui/icons-material";
import { Box, Button, Chip, Dialog, DialogActions, DialogContent, DialogTitle, MenuItem, Paper, Stack, TextField, Typography } from "@mui/material";
import type { Script } from "../api/types";
import { api } from "../api/vibe";
import { SectionHeader } from "../components/SectionHeader";

const languages = ["python", "javascript", "typescript"];

export function ScriptsView({ scripts, onChanged }: { scripts: Script[]; onChanged: () => void }) {
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState<Script | null>(null);
  const [draft, setDraft] = useState({
    name: "",
    slug: "",
    description: "",
    language: "python",
    main_task_md: "",
    source_code: "",
    env_text: "",
  });

  function edit(script?: Script) {
    setSelected(script ?? null);
    setDraft(
      script
        ? {
            name: script.name,
            slug: script.slug,
            description: script.description ?? "",
            language: script.language,
            main_task_md: script.main_task_md,
            source_code: script.source_code,
            env_text: script.env_text,
          }
        : { name: "", slug: "", description: "", language: "python", main_task_md: "", source_code: "", env_text: "" },
    );
    setOpen(true);
  }

  async function save() {
    if (selected) {
      await api.updateScript(selected.id, draft);
    } else {
      await api.createScript(draft);
    }
    setOpen(false);
    onChanged();
  }

  return (
    <Stack spacing={2}>
      <SectionHeader
        title="Scripts"
        subtitle="Editable workspace scripts that can run as plan steps."
        action={<Button startIcon={<Add />} variant="contained" onClick={() => edit()}>Add script</Button>}
      />
      <Stack spacing={1}>
        {scripts.map((script) => (
          <Paper key={script.id} variant="outlined" sx={{ p: 1.5, cursor: "pointer" }} onClick={() => edit(script)}>
            <Stack direction="row" justifyContent="space-between" spacing={1} alignItems="center">
              <Box sx={{ minWidth: 0 }}>
                <Typography fontWeight={850}>{script.name}</Typography>
                <Typography variant="body2" color="text.secondary">{script.description || script.slug}</Typography>
              </Box>
              <Stack direction="row" spacing={0.75} alignItems="center">
                <Chip size="small" label={script.language} />
                <Button
                  size="small"
                  color="error"
                  startIcon={<DeleteOutline />}
                  onClick={(event) => {
                    event.stopPropagation();
                    void api.deleteScript(script.id).then(onChanged);
                  }}
                >
                  Delete
                </Button>
              </Stack>
            </Stack>
          </Paper>
        ))}
        {scripts.length === 0 && <Typography color="text.secondary">No scripts yet.</Typography>}
      </Stack>

      <Dialog open={open} onClose={() => setOpen(false)} fullWidth maxWidth="md">
        <DialogTitle>{selected ? "Edit script" : "Add script"}</DialogTitle>
        <DialogContent>
          <Stack spacing={1.25} sx={{ pt: 1 }}>
            <TextField label="Name" value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} />
            <TextField label="Slug" value={draft.slug} onChange={(event) => setDraft({ ...draft, slug: event.target.value })} />
            <TextField label="Description" value={draft.description} onChange={(event) => setDraft({ ...draft, description: event.target.value })} />
            <TextField select label="Language" value={draft.language} onChange={(event) => setDraft({ ...draft, language: event.target.value })}>
              {languages.map((language) => <MenuItem key={language} value={language}>{language}</MenuItem>)}
            </TextField>
            <TextField label="Main task" value={draft.main_task_md} multiline minRows={3} onChange={(event) => setDraft({ ...draft, main_task_md: event.target.value })} />
            <TextField label="Source" value={draft.source_code} multiline minRows={10} onChange={(event) => setDraft({ ...draft, source_code: event.target.value })} />
            <TextField label=".env" value={draft.env_text} multiline minRows={4} onChange={(event) => setDraft({ ...draft, env_text: event.target.value })} />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOpen(false)}>Cancel</Button>
          <Button variant="contained" disabled={!draft.name.trim()} onClick={() => void save()}>Save</Button>
        </DialogActions>
      </Dialog>
    </Stack>
  );
}
