import type { CheckState } from "../runModel";

const LABELS: Record<CheckState, string> = {
  running: "running",
  passed: "passed",
  failed: "failed",
  error: "error",
  timed_out: "timed out",
};

export function OutcomeChip({ state }: { state: CheckState }) {
  return (
    <span className={`chip chip-${state}`}>
      {state === "running" && <span className="spinner" aria-hidden />}
      {LABELS[state]}
    </span>
  );
}
