/**
 * Recorded-run mode: the same UI, replaying real live runs from static JSON files, so the demo
 * can be hosted for free with no backend and no model spend.
 */
import type { Example, RunResult, RunStatus, ServerEvent } from "./types";

export interface Recording {
  id: string;
  description: string;
  recorded: string;
  result: RunResult;
  events: { type: string; data: Record<string, any> }[];
}

export interface ReplayIndex {
  description: string;
  recordings: { id: string; description: string; file: string }[];
}

type Schedule = (fn: () => void, ms: number) => unknown;

/** How long to pause before showing an event, so a person can follow the run. */
export function delayFor(event: { type: string; data: Record<string, any> }): number {
  if (event.data?.branch === "validation") return 0;
  switch (event.type) {
    case "call_sites_found":
    case "dependencies_found":
    case "research_finished":
    case "scenarios_planned":
    case "scenario_written":
    case "scenario_triaged":
    case "scenario_fixed":
    case "failure_reproduced":
    case "repairs_planned":
    case "candidate_applied":
      return 900;
    case "run_finished":
      return 250;
    case "run_started":
      return 40;
    default:
      return 150;
  }
}

/** Plays recorded events in order; returns a function that stops the replay. */
export function replayEvents(
  events: { type: string; data: Record<string, any> }[],
  onEvent: (event: ServerEvent) => void,
  onEnd: () => void,
  schedule: Schedule = (fn, ms) => setTimeout(fn, ms),
): () => void {
  let stopped = false;
  const step = (index: number) => {
    if (stopped) return;
    if (index >= events.length) {
      onEnd();
      return;
    }
    const event = events[index];
    schedule(() => {
      if (stopped) return;
      onEvent({ seq: index, type: event.type, data: event.data });
      step(index + 1);
    }, delayFor(event));
  };
  step(0);
  return () => {
    stopped = true;
  };
}

const BASE = "./replays/";
let index: Promise<ReplayIndex> | null = null;
const recordings = new Map<string, Promise<Recording>>();

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(BASE + path);
  if (!response.ok) throw new Error(`could not load ${path} (${response.status})`);
  return response.json() as Promise<T>;
}

export const loadIndex = () => (index ??= getJson<ReplayIndex>("index.json"));

export async function loadRecording(id: string): Promise<Recording> {
  if (!recordings.has(id)) {
    const entry = (await loadIndex()).recordings.find((r) => r.id === id);
    if (!entry) throw new Error(`unknown recording ${id}`);
    recordings.set(id, getJson<Recording>(entry.file));
  }
  return recordings.get(id)!;
}

export async function replayExamples(): Promise<Example[]> {
  return (await loadIndex()).recordings.map((r) => ({ id: r.id, description: r.description }));
}

export async function replayStatus(id: string): Promise<RunStatus> {
  const recording = await loadRecording(id);
  return { id, example: id, state: "finished", error: null, result: recording.result };
}
