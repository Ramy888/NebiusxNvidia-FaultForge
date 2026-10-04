import type { RunModel } from "../runModel";

/** What the agent did before injecting faults: discovery, research, writing and reviewing tests. */
export function Activity({ model }: { model: RunModel }) {
  if (model.activity.length === 0) return null;
  const live = model.phase === "preparing";
  const items = (
    <ol className="activity">
      {model.activity.map((line, i) => (
        <li key={i}>{line}</li>
      ))}
      {live && (
        <li className="activity-now">
          <span className="spinner" aria-hidden /> working…
        </li>
      )}
    </ol>
  );
  return live ? (
    <section className="panel" aria-live="polite" aria-labelledby="activity-heading">
      <h2 id="activity-heading">Preparing: Nemotron is reading the service</h2>
      {items}
    </section>
  ) : (
    <details className="panel activity-done">
      <summary>Preparation ({model.activity.length} steps)</summary>
      {items}
    </details>
  );
}
