import type { ServerEvent } from "./types";

export type CheckState = "running" | "passed" | "failed" | "error" | "timed_out";

export interface CheckNode {
  name: string;
  state: CheckState;
  message: string;
  durationS?: number;
}

export interface BranchNode {
  id: string;
  kind: "baseline" | "candidate";
  summary: string;
  diff: string;
  checks: Record<string, CheckNode>;
  checkOrder: string[];
}

export type Phase = "idle" | "baseline" | "planning" | "replaying" | "done" | "failed";

export interface RunModel {
  phase: Phase;
  repo: string;
  scenarios: { id: string; title: string; fault: string }[];
  branches: Record<string, BranchNode>;
  branchOrder: string[];
  strategies: { id: string; summary: string }[];
  failure?: { scenario: string; message: string };
  discarded: { scenario: string; reason: string }[];
  research: { title: string; url: string }[];
  dependency?: string;
  status?: string;
  winner?: string | null;
  error?: string;
}

export const initialModel = (): RunModel => ({
  phase: "idle",
  repo: "",
  scenarios: [],
  branches: {},
  branchOrder: [],
  strategies: [],
  discarded: [],
  research: [],
});

function withBranch(model: RunModel, id: string, patch: Partial<BranchNode> = {}): RunModel {
  const existing = model.branches[id];
  const branch: BranchNode = existing
    ? { ...existing, ...patch }
    : {
        id,
        kind: id === "baseline" ? "baseline" : "candidate",
        summary: "",
        diff: "",
        checks: {},
        checkOrder: [],
        ...patch,
      };
  return {
    ...model,
    branches: { ...model.branches, [id]: branch },
    branchOrder: existing ? model.branchOrder : [...model.branchOrder, id],
  };
}

function withCheck(model: RunModel, branchId: string, check: CheckNode): RunModel {
  const next = withBranch(model, branchId);
  const branch = next.branches[branchId];
  const known = check.name in branch.checks;
  return withBranch(next, branchId, {
    checks: { ...branch.checks, [check.name]: { ...branch.checks[check.name], ...check } },
    checkOrder: known ? branch.checkOrder : [...branch.checkOrder, check.name],
  });
}

/** Folds one server event into the run model. Pure, so the UI can replay any stream. */
export function applyEvent(model: RunModel, event: ServerEvent): RunModel {
  const d = event.data;
  switch (event.type) {
    case "pipeline_started":
      return withBranch(
        { ...model, phase: "baseline", repo: d.repo, scenarios: d.scenarios ?? [] },
        "baseline",
      );
    case "dependencies_found":
      return { ...model, dependency: (d.dependencies ?? [])[0] };
    case "research_finished":
      return { ...model, research: d.sources ?? [] };
    case "run_started":
      return withCheck(model, d.branch, { name: d.check, state: "running", message: "" });
    case "run_finished":
      return withCheck(model, d.branch, {
        name: d.check,
        state: d.outcome,
        message: d.message ?? "",
        durationS: d.duration_s,
      });
    case "scenario_discarded":
      return {
        ...model,
        discarded: [...model.discarded, { scenario: d.scenario, reason: d.reason }],
      };
    case "failure_reproduced":
      return {
        ...model,
        phase: "planning",
        failure: { scenario: d.scenario, message: d.message },
      };
    case "repairs_planned":
      return { ...model, strategies: d.strategies ?? [] };
    case "candidate_applied":
      return { ...withBranch(model, d.candidate, { summary: d.summary, diff: d.diff }), phase: "replaying" };
    case "pipeline_finished":
      return { ...model, phase: "done", status: d.status, winner: d.winner };
    case "run_failed":
      return { ...model, phase: "failed", error: d.error };
    default:
      return model;
  }
}
