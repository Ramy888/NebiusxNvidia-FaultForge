import { render, screen } from "@testing-library/react";
import { applyEvent, initialModel } from "../runModel";
import type { RunResult, ServerEvent } from "../types";
import { AttemptTree } from "./AttemptTree";
import { Evidence } from "./Evidence";

const events: ServerEvent[] = [
  { seq: 0, type: "pipeline_started", data: { repo: "order-service", scenarios: [{ id: "t", title: "Response times out", fault: "timeout" }] } },
  { seq: 1, type: "run_finished", data: { branch: "baseline", check: "t", outcome: "failed", message: "2 fulfillments" } },
  { seq: 2, type: "candidate_applied", data: { candidate: "idem", summary: "Send an idempotency key", diff: "+x" } },
  { seq: 3, type: "run_finished", data: { branch: "idem", check: "t", outcome: "passed", message: "" } },
  { seq: 4, type: "pipeline_finished", data: { status: "repaired", winner: "idem" } },
];
const check = (outcome: "passed" | "failed", message = "") => ({ outcome, message, duration_s: 0.1, output: "" });
const RESULT: RunResult = {
  repo: "order-service",
  status: "repaired",
  target: "t",
  winner: "idem",
  existing_tests: check("passed"),
  scenarios: [{ id: "t", title: "Response times out", fault: "timeout", test_path: "tests/test_ff_t.py", test_code: "def test(): ...", baseline: check("failed", "one order created 2 fulfillments") }],
  candidates: [{ id: "idem", summary: "Send an idempotency key", accepted: true, rejection_reason: "", diff: "--- a/f.py\n+++ b/f.py\n+    headers=key,", diff_lines: 1, fixed: ["t"], regressed: [], existing_tests: check("passed"), scenarios: { t: check("passed") } }],
  dependency: null,
  research: [{ title: "Idempotent requests", url: "https://docs.example" }],
  markdown: "",
};

test("attempt tree shows the original code, each repair and the proposed fix", () => {
  const model = events.reduce(applyEvent, initialModel());
  render(<AttemptTree model={model} selected={null} onSelect={() => {}} />);

  expect(screen.getByText("order-service")).toBeTruthy();
  expect(screen.getByText("Send an idempotency key")).toBeTruthy();
  expect(screen.getByText("Proposed fix")).toBeTruthy();
  expect(screen.getByText("2 fulfillments")).toBeTruthy();
});

test("evidence shows what broke, before and after, the patch and sources", () => {
  const { container } = render(<Evidence result={RESULT} candidateId={null} />);

  expect(screen.getByText("one order created 2 fulfillments")).toBeTruthy();
  expect(screen.getByText("verified")).toBeTruthy();
  expect(container.querySelector(".diff-add")?.textContent).toContain("+    headers=key,");
  expect(screen.getByRole("link", { name: "Idempotent requests" })).toBeTruthy();
});

test("the last step reads as done once the run has finished", async () => {
  const { PhaseBar } = await import("./PhaseBar");
  const { container } = render(<PhaseBar phase="done" />);

  expect(container.querySelectorAll(".phase-done")).toHaveLength(4);
});
