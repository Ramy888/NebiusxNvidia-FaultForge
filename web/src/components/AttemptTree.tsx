import type { BranchNode, RunModel } from "../runModel";
import { sentence } from "../text";
import { OutcomeChip } from "./Outcome";

function checkLabel(model: RunModel, name: string): string {
  if (name === "existing_tests") return "Existing test suite";
  return sentence(model.scenarios.find((s) => s.id === name)?.title ?? name);
}

function Branch({
  model,
  branch,
  selected,
  onSelect,
}: {
  model: RunModel;
  branch: BranchNode;
  selected: boolean;
  onSelect: (id: string) => void;
}) {
  const isWinner = model.winner === branch.id;
  return (
    <li className={`branch ${selected ? "branch-selected" : ""}`}>
      <button className="branch-head" onClick={() => onSelect(branch.id)}>
        <span className="branch-kind">{branch.kind === "baseline" ? "Original code" : "Repair"}</span>
        <span className="branch-title">
          {branch.kind === "baseline" ? model.repo : branch.summary || branch.id}
        </span>
        {isWinner && <span className="badge-winner">Proposed fix</span>}
      </button>
      <ul className="checks">
        {branch.checkOrder.map((name) => {
          const check = branch.checks[name];
          return (
            <li key={name} className="check">
              <OutcomeChip state={check.state} />
              <span className="check-name">{checkLabel(model, name)}</span>
              {check.message && check.state !== "passed" && (
                <span className="check-message">{check.message}</span>
              )}
            </li>
          );
        })}
      </ul>
    </li>
  );
}

export function AttemptTree({
  model,
  selected,
  onSelect,
}: {
  model: RunModel;
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  const [baseline, ...candidates] = model.branchOrder;
  if (!baseline) return null;
  return (
    <section className="panel" aria-labelledby="tree-heading">
      <h2 id="tree-heading">Every attempt, in its own sandbox branch</h2>
      <ul className="tree">
        <Branch
          model={model}
          branch={model.branches[baseline]}
          selected={selected === baseline}
          onSelect={onSelect}
        />
        {candidates.length > 0 && (
          <li className="tree-children">
            <ul className="tree">
              {candidates.map((id) => (
                <Branch
                  key={id}
                  model={model}
                  branch={model.branches[id]}
                  selected={selected === id}
                  onSelect={onSelect}
                />
              ))}
            </ul>
          </li>
        )}
      </ul>
      {model.discarded.length > 0 && (
        <p className="note">
          Discarded {model.discarded.length} generated test(s) that failed for their own bugs.
        </p>
      )}
    </section>
  );
}
