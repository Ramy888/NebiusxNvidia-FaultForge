import type { CandidateResult, CheckResult, RunResult } from "../types";
import { plural, sentence } from "../text";
import { Diff } from "./Diff";
import { OutcomeChip } from "./Outcome";

const HEADLINES: Record<RunResult["status"], string> = {
  repaired: "A repair fixed the reproduced failure without breaking existing tests.",
  no_repair: "The failure was reproduced, but no repair passed verification.",
  no_failure: "No injected failure broke the application.",
  broken_baseline: "The existing tests fail before any fault is injected.",
  no_valid_scenarios: "Every generated failure test was discarded because the test itself was broken.",
};

function Transition({ before, after }: { before: CheckResult; after: CheckResult }) {
  return (
    <span className="transition">
      <OutcomeChip state={before.outcome} />
      <span aria-hidden>→</span>
      <OutcomeChip state={after.outcome} />
    </span>
  );
}

export function Evidence({
  result,
  candidateId,
  actions,
}: {
  result: RunResult;
  candidateId: string | null;
  actions?: React.ReactNode;
}) {
  const candidate: CandidateResult | undefined =
    result.candidates.find((c) => c.id === candidateId) ??
    result.candidates.find((c) => c.id === result.winner) ??
    result.candidates[0];
  const target = result.scenarios.find((s) => s.id === result.target);

  return (
    <section className="panel evidence" aria-labelledby="evidence-heading">
      <h2 id="evidence-heading">Evidence</h2>
      <p className={`verdict verdict-${result.status}`}>{HEADLINES[result.status]}</p>

      {result.dependency && (
        <p className="note">
          Dependency <strong>{result.dependency.name}</strong>, called from{" "}
          <code>{result.dependency.call_sites.join(", ")}</code>; operation at risk{" "}
          <code>{result.dependency.operation}</code>.
        </p>
      )}

      <h3>What broke</h3>
      <ul className="failures">
        {result.scenarios.map((s) => (
          <li key={s.id}>
            <span className="fault">{s.fault.replace("_", " ")}</span>
            <span>{sentence(s.title)}</span>
            {s.baseline.outcome !== "passed" ? (
              <blockquote>{s.baseline.message}</blockquote>
            ) : (
              <span className="note">held up</span>
            )}
          </li>
        ))}
      </ul>

      {candidate && (
        <>
          <h3>
            Repair <code>{candidate.id}</code>
            {candidate.accepted ? (
              <span className="badge-ok">verified</span>
            ) : (
              <span className="badge-bad">rejected: {candidate.rejection_reason}</span>
            )}
          </h3>
          <p>{candidate.summary}</p>
          <table className="matrix">
            <thead>
              <tr>
                <th scope="col">Check</th>
                <th scope="col">Original → repaired</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>Existing test suite</td>
                <td>
                  <Transition before={result.existing_tests} after={candidate.existing_tests} />
                </td>
              </tr>
              {result.scenarios.map((s) => (
                <tr key={s.id}>
                  <td>{sentence(s.title)}</td>
                  <td>
                    <Transition before={s.baseline} after={candidate.scenarios[s.id]} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <h3>Patch ({plural(candidate.diff_lines, "line")} changed)</h3>
          <Diff diff={candidate.diff} />
        </>
      )}

      {target && (
        <details>
          <summary>
            Regression test <code>{target.test_path}</code>
          </summary>
          <pre className="code">{target.test_code}</pre>
        </details>
      )}

      {result.research.length > 0 && (
        <>
          <h3>Research on the real service (Tavily)</h3>
          <ul>
            {result.research.map((source) => (
              <li key={source.url}>
                <a href={source.url} target="_blank" rel="noreferrer">
                  {source.title}
                </a>
              </li>
            ))}
          </ul>
        </>
      )}
      {actions}
    </section>
  );
}
