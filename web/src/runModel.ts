import type { ServerEvent } from "./types";

export type CheckState = "running" | "passed" | "failed" | "error" | "timed_out" | "discarded";

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

export type Phase = "idle" | "preparing" | "baseline" | "planning" | "replaying" | "done" | "failed";

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
  /** Human-readable log of the preparation steps (live mode): discovery, research, test writing. */
  activity: string[];
  written: Record<string, { fault: string; title: string }>;
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
  activity: [],
  written: {},
});

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;
const faultName = (fault: string) => fault.replace(/_/g, " ");

function note(model: RunModel, line: string): RunModel {
  const phase = model.phase === "idle" ? "preparing" : model.phase;
  return { ...model, phase, activity: [...model.activity, line] };
}

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
  // Generated tests are checked once before the real baseline; those runs are not attempts.
  if (d.branch === "validation") return model;
  switch (event.type) {
    case "pipeline_started":
      return withBranch(
        { ...model, phase: "baseline", repo: d.repo, scenarios: d.scenarios ?? [] },
        "baseline",
      );
    case "call_sites_found":
      return note(model, `Found ${plural((d.sites ?? []).length, "outbound HTTP call")}`);
    case "no_dependencies":
      return note(model, "No outbound HTTP dependency found");
    case "dependencies_found": {
      const dependency = (d.dependencies ?? [])[0];
      return note({ ...model, dependency }, dependency ? `Dependency: ${dependency}` : "No dependency identified");
    }
    case "research_finished":
      return note(
        { ...model, research: d.sources ?? [] },
        `Researched how it fails: ${plural((d.sources ?? []).length, "source")}`,
      );
    case "research_failed":
    case "research_skipped":
      return note(model, "Web research unavailable; continuing without it");
    case "scenarios_planned":
      return note(model, `Planned ${plural((d.scenarios ?? []).length, "failure scenario")}`);
    case "scenario_written":
      return note(
        { ...model, written: { ...model.written, [d.scenario]: { fault: d.fault, title: d.title } } },
        `Wrote a ${faultName(d.fault)} test: ${d.title}`,
      );
    case "scenario_triaged": {
      const title = model.written[d.scenario]?.title ?? d.scenario;
      return d.verdict === "test_mistake"
        ? note(model, `Review: the ${title} test had a mistake (${d.reason}); asked for a fix`)
        : note(model, `Review: ${title} is a real application bug`);
    }
    case "scenario_fixed":
      return note(model, `Fixed the ${faultName(d.fault)} test`);
    case "run_started":
      return withCheck(model, d.branch, { name: d.check, state: "running", message: "" });
    case "run_finished":
      return withCheck(model, d.branch, {
        name: d.check,
        state: d.outcome,
        message: d.message ?? "",
        durationS: d.duration_s,
      });
    case "scenario_discarded": {
      const reason = String(d.reason ?? "").split("\n")[0].slice(0, 120);
      const baseline = model.branches.baseline;
      let next: RunModel = {
        ...model,
        discarded: [...model.discarded, { scenario: d.scenario, reason: d.reason }],
      };
      if (baseline?.checks[d.scenario]) {
        next = withCheck(next, "baseline", { name: d.scenario, state: "discarded", message: reason });
      }
      return model.phase === "idle" || model.phase === "preparing"
        ? note(next, `Discarded a broken test: ${reason}`)
        : next;
    }
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
