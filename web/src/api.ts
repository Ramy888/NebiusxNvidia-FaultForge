import type { Example, RunStatus, ServerEvent } from "./types";

async function json<T>(response: Response): Promise<T> {
  if (!response.ok) throw new Error(`${response.status} ${await response.text()}`);
  return response.json() as Promise<T>;
}

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
  source.onerror = () => {
    source.close();
    onEnd();
  };
  return () => source.close();
}
