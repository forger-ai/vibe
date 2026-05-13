import { useState } from "react";
import { Add, DeleteOutline } from "@mui/icons-material";
import { Box, Button, Chip, Dialog, DialogActions, DialogContent, DialogTitle, MenuItem, Paper, Stack, TextField, Typography } from "@mui/material";
import type { StepType } from "../api/types";
import { api } from "../api/vibe";
import { SectionHeader } from "../components/SectionHeader";

const responsibleOptions = ["agent", "multiagents", "human", "script", "command"];

export function StepTypesView({ stepTypes, onChanged }: { stepTypes: StepType[]; onChanged: () => void }) {
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState<StepType | null>(null);
  const [draft, setDraft] = useState({
    name: "",
    description: "",
    context_md: "",
    main_task_md: "",
    responsible: "agent",
    git_work: true,
  });

  function edit(stepType?: StepType) {
    setSelected(stepType ?? null);
    setDraft(
      stepType
        ? {
            name: stepType.name,
            description: stepType.description ?? "",
            context_md: stepType.context_md,
            main_task_md: stepType.main_task_md,
            responsible: stepType.responsible,
            git_work: stepType.git_work,
          }
        : { name: "", description: "", context_md: "", main_task_md: "", responsible: "agent", git_work: true },
    );
    setOpen(true);
  }

  async function save() {
    if (selected) {
      await api.updateStepType(selected.id, draft);
    } else {
      await api.createStepType(draft);
    }
    setOpen(false);
    onChanged();
  }

  return (
    <Stack spacing={2}>
      <SectionHeader
        title="Step Types"
        subtitle="Execution contracts used by plan steps."
        action={<Button startIcon={<Add />} variant="contained" onClick={() => edit()}>Add type</Button>}
      />
      <Stack spacing={1}>
        {stepTypes.map((stepType) => (
          <Paper key={stepType.id} variant="outlined" sx={{ p: 1.5, cursor: "pointer" }} onClick={() => edit(stepType)}>
            <Stack direction="row" spacing={1} justifyContent="space-between" alignItems="center">
              <Box sx={{ minWidth: 0 }}>
                <Typography fontWeight={850}>{stepType.name}</Typography>
                <Typography variant="body2" color="text.secondary">{stepType.description || "No description"}</Typography>
              </Box>
              <Stack direction="row" spacing={0.75} alignItems="center">
                <Chip size="small" label={stepType.responsible} />
                <Chip size="small" label={stepType.git_work ? "git" : "no git"} />
                <Button
                  size="small"
                  color="error"
                  startIcon={<DeleteOutline />}
                  onClick={(event) => {
                    event.stopPropagation();
                    void api.deleteStepType(stepType.id).then(onChanged);
                  }}
                >
                  Delete
                </Button>
              </Stack>
            </Stack>
          </Paper>
        ))}
      </Stack>

      <Dialog open={open} onClose={() => setOpen(false)} fullWidth maxWidth="md">
        <DialogTitle>{selected ? "Edit step type" : "Add step type"}</DialogTitle>
        <DialogContent>
          <Stack spacing={1.25} sx={{ pt: 1 }}>
            <TextField label="Name" value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} />
            <TextField label="Description" value={draft.description} onChange={(event) => setDraft({ ...draft, description: event.target.value })} />
            <TextField select label="Responsible" value={draft.responsible} onChange={(event) => setDraft({ ...draft, responsible: event.target.value })}>
              {responsibleOptions.map((option) => <MenuItem key={option} value={option}>{option}</MenuItem>)}
            </TextField>
            <TextField select label="Git work" value={draft.git_work ? "yes" : "no"} onChange={(event) => setDraft({ ...draft, git_work: event.target.value === "yes" })}>
              <MenuItem value="yes">Yes</MenuItem>
              <MenuItem value="no">No</MenuItem>
            </TextField>
            <TextField label="Main task" value={draft.main_task_md} multiline minRows={4} onChange={(event) => setDraft({ ...draft, main_task_md: event.target.value })} />
            <TextField label="Context" value={draft.context_md} multiline minRows={3} onChange={(event) => setDraft({ ...draft, context_md: event.target.value })} />
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
