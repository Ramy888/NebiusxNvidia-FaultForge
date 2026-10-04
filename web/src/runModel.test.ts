import { applyEvent, initialModel, type RunModel } from "./runModel";
import type { ServerEvent } from "./types";

let seq = 0;
const ev = (type: string, data: Record<string, unknown> = {}): ServerEvent => ({
  seq: seq++,
  type,
  data,
});
const fold = (events: ServerEvent[]): RunModel => events.reduce(applyEvent, initialModel());

const STARTED = ev("pipeline_started", {
  repo: "order-service",
  scenarios: [{ id: "timeout_duplicate", title: "response times out", fault: "timeout" }],
});

test("pipeline start records scenarios and enters the baseline phase", () => {
  const model = fold([STARTED]);

  expect(model.phase).toBe("baseline");
  expect(model.scenarios.map((s) => s.id)).toEqual(["timeout_duplicate"]);
});

test("baseline checks appear as running, then settle with their outcome", () => {
  const running = fold([
    STARTED,
    ev("run_started", { branch: "baseline", check: "timeout_duplicate", snapshot: "s1" }),
  ]);
  expect(running.branches.baseline.checks.timeout_duplicate.state).toBe("running");

  const settled = applyEvent(
    running,
    ev("run_finished", {
      branch: "baseline",
      check: "timeout_duplicate",
      outcome: "failed",
      message: "one order created 2 fulfillments",
      duration_s: 0.4,
    }),
  );
  expect(settled.branches.baseline.checks.timeout_duplicate).toMatchObject({
    state: "failed",
    message: "one order created 2 fulfillments",
  });
});

test("a reproduced failure is remembered and moves to planning", () => {
  const model = fold([
    STARTED,
    ev("failure_reproduced", { scenario: "timeout_duplicate", message: "2 fulfillments" }),
  ]);

  expect(model.phase).toBe("planning");
  expect(model.failure).toEqual({ scenario: "timeout_duplicate", message: "2 fulfillments" });
});

test("applied candidates become branches with their summary and diff, in order", () => {
  const model = fold([
    STARTED,
    ev("repairs_planned", { strategies: [{ id: "a", summary: "A" }, { id: "b", summary: "B" }] }),
    ev("candidate_applied", { candidate: "a", summary: "A", diff: "+x" }),
    ev("candidate_applied", { candidate: "b", summary: "B", diff: "-y" }),
  ]);

  expect(model.phase).toBe("replaying");
  expect(model.branchOrder).toEqual(["baseline", "a", "b"]);
  expect(model.branches.a).toMatchObject({ kind: "candidate", summary: "A", diff: "+x" });
});

test("pipeline finish records the status and winner", () => {
  const model = fold([
    STARTED,
    ev("pipeline_finished", { status: "repaired", winner: "a" }),
  ]);

  expect(model.phase).toBe("done");
  expect(model).toMatchObject({ status: "repaired", winner: "a" });
});

test("discarded scenarios and research sources are kept for display", () => {
  const model = fold([
    STARTED,
    ev("research_finished", { sources: [{ title: "Docs", url: "https://d" }] }),
    ev("scenario_discarded", { scenario: "x", reason: "NameError" }),
  ]);

  expect(model.research).toEqual([{ title: "Docs", url: "https://d" }]);
  expect(model.discarded).toEqual([{ scenario: "x", reason: "NameError" }]);
});

test("a failed run is terminal and keeps the error", () => {
  const model = fold([STARTED, ev("run_failed", { error: "boom" })]);

  expect(model).toMatchObject({ phase: "failed", error: "boom" });
});

test("preparation events build a readable activity feed and a preparing phase", () => {
  const model = fold([
    ev("call_sites_found", { sites: ["orders/fulfillment.py:FulfillmentClient.create"] }),
    ev("dependencies_found", { dependencies: ["Fulfillment API"] }),
    ev("research_finished", { sources: [{ title: "Stripe", url: "https://s" }] }),
    ev("scenarios_planned", { scenarios: [{ fault: "timeout" }, { fault: "malformed" }] }),
    ev("scenario_written", { scenario: "t1", fault: "timeout", title: "times out" }),
    ev("scenario_triaged", { scenario: "t1", verdict: "test_mistake", reason: "reads unknown order" }),
    ev("scenario_fixed", { scenario: "t1", fault: "timeout", title: "times out" }),
  ]);

  expect(model.phase).toBe("preparing");
  expect(model.activity).toEqual([
    "Found 1 outbound HTTP call",
    "Dependency: Fulfillment API",
    "Researched how it fails: 1 source",
    "Planned 2 failure scenarios",
    "Wrote a timeout test: times out",
    "Review: the times out test had a mistake (reads unknown order); asked for a fix",
    "Fixed the timeout test",
  ]);
});

test("discarded scenarios are marked in the tree instead of looking like failures", () => {
  const model = fold([
    STARTED,
    ev("run_finished", { branch: "baseline", check: "timeout_duplicate", outcome: "failed", message: "KeyError" }),
    ev("scenario_discarded", { scenario: "timeout_duplicate", reason: "KeyError: 'id' in the test" }),
  ]);

  expect(model.branches.baseline.checks.timeout_duplicate.state).toBe("discarded");
});

test("validation runs during preparation do not appear in the attempt tree", () => {
  const model = fold([
    ev("run_finished", { branch: "validation", check: "t1", outcome: "failed", message: "x" }),
    STARTED,
  ]);

  expect(model.branchOrder).toEqual(["baseline"]);
  expect(model.branches.baseline.checkOrder).toEqual([]);
});
