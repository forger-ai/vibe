import { useState } from "react";
import { Add, Sync } from "@mui/icons-material";
import { Alert, Button, Paper, Stack, TextField, Typography } from "@mui/material";
import type { GitRepository } from "../api/types";
import { api } from "../api/vibe";
import { SectionHeader } from "../components/SectionHeader";

export function RepositoriesView({
  repositories,
  onChanged,
}: {
  repositories: GitRepository[];
  onChanged: () => void;
}) {
  const [name, setName] = useState("");
  const [remoteUrl, setRemoteUrl] = useState("");
  const [defaultBranch, setDefaultBranch] = useState("main");
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function create() {
    setError(null);
    await api.createRepository({
      name,
      remote_url: remoteUrl,
      default_branch: defaultBranch,
    });
    setName("");
    setRemoteUrl("");
    setDefaultBranch("main");
    await onChanged();
  }

  async function sync(id: string) {
    setBusyId(id);
    setError(null);
    try {
      await api.syncRepository(id);
      await onChanged();
    } catch (syncError) {
      setError(syncError instanceof Error ? syncError.message : "Repository sync failed");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <Stack spacing={2}>
      <SectionHeader
        title="Repositories"
        subtitle="Register Git remotes. Credentials stay in local Git, SSH, HTTPS, or gh configuration."
      />
      {error ? <Alert severity="error">{error}</Alert> : null}
      <Paper sx={{ p: 2, borderRadius: 1 }}>
        <Stack direction={{ xs: "column", md: "row" }} spacing={1.25}>
          <TextField label="Name" value={name} onChange={(event) => setName(event.target.value)} />
          <TextField
            label="Remote URL"
            value={remoteUrl}
            fullWidth
            onChange={(event) => setRemoteUrl(event.target.value)}
          />
          <TextField
            label="Default branch"
            value={defaultBranch}
            sx={{ minWidth: 160 }}
            onChange={(event) => setDefaultBranch(event.target.value)}
          />
          <Button
            variant="contained"
            startIcon={<Add />}
            disabled={!name.trim() || !remoteUrl.trim()}
            onClick={() => void create()}
          >
            Add
          </Button>
        </Stack>
      </Paper>
      <Stack spacing={1}>
        {repositories.map((repo) => (
          <Paper key={repo.id} sx={{ p: 1.5, borderRadius: 1 }}>
            <Stack direction={{ xs: "column", md: "row" }} justifyContent="space-between" spacing={1}>
              <Stack spacing={0.25} sx={{ minWidth: 0 }}>
                <Typography fontWeight={850}>{repo.name}</Typography>
                <Typography variant="body2" color="text.secondary" noWrap>
                  {repo.remote_url}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  branch {repo.default_branch} · {repo.local_path || "not synced"}
                </Typography>
              </Stack>
              <Button
                startIcon={<Sync />}
                disabled={busyId === repo.id}
                onClick={() => void sync(repo.id)}
              >
                Sync {repo.default_branch}
              </Button>
            </Stack>
          </Paper>
        ))}
      </Stack>
    </Stack>
  );
}
