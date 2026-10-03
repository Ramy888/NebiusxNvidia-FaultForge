import type { Phase } from "../runModel";

const STEPS: { phase: Phase; label: string }[] = [
  { phase: "baseline", label: "Inject failures" },
  { phase: "planning", label: "Plan repairs" },
  { phase: "replaying", label: "Replay every failure" },
  { phase: "done", label: "Verdict" },
];
const ORDER: Phase[] = ["idle", "baseline", "planning", "replaying", "done"];

export function PhaseBar({ phase }: { phase: Phase }) {
  const current = phase === "failed" ? -1 : ORDER.indexOf(phase);
  return (
    <ol className="phases" aria-label="Run progress">
      {STEPS.map((step) => {
        const index = ORDER.indexOf(step.phase);
        const finished = phase === "done";
        const state =
          index < current || finished ? "done" : index === current ? "active" : "todo";
        return (
          <li key={step.phase} className={`phase phase-${state}`}>
            {step.label}
          </li>
        );
      })}
    </ol>
  );
}
