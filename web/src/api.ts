import { loadIndex, loadRecording, replayEvents, replayExamples, replayStatus } from "./replay";
import type { Example, RunStatus, ServerEvent } from "./types";

/** Built with VITE_REPLAY=1: no backend, the UI replays recorded live runs. */
export const REPLAY = import.meta.env.VITE_REPLAY === "1";

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

export const fetchInfo = (): Promise<ServerInfo> =>
  REPLAY
    ? loadIndex().then((i) => ({ mode: "replay", description: i.description }))
    : fetch("/api/info").then((r) => json<ServerInfo>(r));

export interface ServerInfo {
  mode: string;
  description: string;
  live_runs_left_today?: number;
}

export const fetchExamples = (): Promise<Example[]> =>
  REPLAY ? replayExamples() : fetch("/api/examples").then((r) => json<Example[]>(r));

export const startRun = (example: string, mode?: "demo" | "live"): Promise<{ id: string }> =>
  REPLAY ? Promise.resolve({ id: example }) : fetch("/api/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(mode ? { example, mode } : { example }),
  }).then((r) => json<{ id: string }>(r));

export const fetchRun = (id: string): Promise<RunStatus> =>
  REPLAY ? replayStatus(id) : fetch(`/api/runs/${id}`).then((r) => json<RunStatus>(r));

/** Follows a run's event stream; returns a function that stops listening. */
export function followRun(
  id: string,
  onEvent: (event: ServerEvent) => void,
  onEnd: () => void,
): () => void {
  if (REPLAY) {
    let stop = () => {};
    let cancelled = false;
    loadRecording(id).then(
      (recording) => {
        if (!cancelled) stop = replayEvents(recording.events, onEvent, onEnd);
      },
      () => onEnd(),
    );
    return () => {
      cancelled = true;
      stop();
    };
  }
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
