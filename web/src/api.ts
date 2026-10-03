import type { Example, RunStatus, ServerEvent } from "./types";

async function json<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const text = await response.text();
    let detail = text;
    try {
      detail = (JSON.parse(text) as { detail?: string }).detail ?? text;
    } catch {
      /* not JSON: show the raw text */
    }
    throw new Error(detail || `Request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

export const fetchInfo = () =>
  fetch("/api/info").then((r) => json<{ mode: string; description: string }>(r));

export const fetchExamples = () => fetch("/api/examples").then((r) => json<Example[]>(r));

export const startRun = (example: string) =>
  fetch("/api/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ example }),
  }).then((r) => json<{ id: string }>(r));

export const fetchRun = (id: string) => fetch(`/api/runs/${id}`).then((r) => json<RunStatus>(r));

/** Follows a run's event stream; returns a function that stops listening. */
export function followRun(
  id: string,
  onEvent: (event: ServerEvent) => void,
  onEnd: () => void,
): () => void {
  const source = new EventSource(`/api/runs/${id}/events`);
  source.onmessage = (message) => onEvent(JSON.parse(message.data) as ServerEvent);
  source.addEventListener("end", () => {
    source.close();
    onEnd();
  });
  // On a dropped connection EventSource reconnects by itself and sends Last-Event-ID, which the
  // server uses to resume. Only give up if the browser has stopped retrying.
  source.onerror = () => {
    if (source.readyState === EventSource.CLOSED) onEnd();
  };
  return () => source.close();
}

export interface PullRequestPreview {
  dry_run: boolean;
  branch: string;
  title: string;
  body: string;
  files: string[];
}

export const previewPullRequest = (id: string) =>
  fetch(`/api/runs/${id}/pull-request`, { method: "POST" }).then((r) =>
    json<PullRequestPreview>(r),
  );
