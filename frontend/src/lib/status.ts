export function statusColor(status: string): "default" | "primary" | "success" | "warning" | "error" {
  if (["completed", "idle", "ready"].includes(status)) return "success";
  if (["running", "active", "queued"].includes(status)) return "primary";
  if (["draft", "pending"].includes(status)) return "warning";
  if (["failed", "canceled", "error"].includes(status)) return "error";
  return "default";
}

export function shortId(id: string): string {
  return id.slice(0, 8);
}
