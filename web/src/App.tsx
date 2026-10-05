import { useEffect, useReducer, useRef, useState } from "react";
import {
  fetchExamples,
  fetchInfo,
  fetchRun,
  followRun,
  type ServerInfo,
  startRun,
} from "./api";
import { Activity } from "./components/Activity";
import { AttemptTree } from "./components/AttemptTree";
import { Evidence } from "./components/Evidence";
import { PhaseBar } from "./components/PhaseBar";
import { PullRequest } from "./components/PullRequest";
import { applyEvent, initialModel, type RunModel } from "./runModel";
import type { Example, RunResult, ServerEvent } from "./types";

type Action = { kind: "reset" } | { kind: "event"; event: ServerEvent };

function reducer(model: RunModel, action: Action): RunModel {
  return action.kind === "reset" ? initialModel() : applyEvent(model, action.event);
}

export default function App() {
  const [examples, setExamples] = useState<Example[]>([]);
  const [info, setInfo] = useState<ServerInfo | null>(null);
  const [example, setExample] = useState<string>("");
  const [model, dispatch] = useReducer(reducer, undefined, initialModel);
  const [result, setResult] = useState<RunResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [runId, setRunId] = useState<string | null>(null);
  const [runMode, setRunMode] = useState<string | null>(null);
  const stop = useRef<(() => void) | null>(null);

  useEffect(() => {
    fetchInfo().then(setInfo, () => setInfo(null));
    fetchExamples()
      .then((list) => {
        setExamples(list);
        setExample((current) => current || list[0]?.id || "");
      })
      .catch((e: Error) => setError(e.message));
    return () => stop.current?.();
  }, []);

  async function run(mode?: "demo" | "live") {
    stop.current?.();
    dispatch({ kind: "reset" });
    setResult(null);
    setError(null);
    setSelected(null);
    setBusy(true);
    try {
      const { id } = await startRun(example, mode);
      setRunId(id);
      setRunMode(mode ?? info?.mode ?? null);
      stop.current = followRun(
        id,
        (event) => dispatch({ kind: "event", event }),
        async () => {
          const status = await fetchRun(id).catch(() => null);
          if (status?.result) setResult(status.result);
          if (status?.error) setError(status.error);
          setBusy(false);
          fetchInfo().then(setInfo, () => {});
        },
      );
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  return (
    <div className="page">
      <header className="masthead">
        <p className="wordmark">
          Fault<span>Forge</span>
        </p>
        <h1>Find out how your app fails when its dependencies misbehave.</h1>
        <p className="lede">
          FaultForge injects timeouts, rate limits, malformed responses and duplicate deliveries,
          shows exactly what breaks, then replays every failure against competing repairs. Built
          on NVIDIA Nemotron and Nebius Token Factory; every attempt runs in its own sandbox
          branch.
        </p>
        {info && <p className={`mode mode-${info.mode}`}>{info.description}</p>}
      </header>

      <section className="panel picker" aria-labelledby="picker-heading">
        <h2 id="picker-heading">Pick a service</h2>
        <div className="examples" role="radiogroup">
          {examples.map((e) => (
            <label key={e.id} className={`example ${example === e.id ? "example-on" : ""}`}>
              <input
                type="radio"
                name="example"
                value={e.id}
                checked={example === e.id}
                onChange={() => setExample(e.id)}
              />
              <code>{e.id}</code>
              <span>{e.description}</span>
            </label>
          ))}
        </div>
        <div className="actions">
          <button className="primary" onClick={() => run()} disabled={!example || busy}>
            {busy ? "Running…" : "Break it and repair it"}
          </button>
          {info?.mode === "live" && (
            <>
              <button className="secondary" onClick={() => run("demo")} disabled={!example || busy}>
                Watch the scripted run
              </button>
              <span className="note">
                {info.live_runs_left_today ?? 0} live runs left today
              </span>
            </>
          )}
        </div>
      </section>

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}

      {model.phase !== "idle" && (
        <>
          {runMode === "demo" && info?.mode === "live" && (
            <p className="mode">Scripted run: prewritten model answers, no Nemotron calls, no credit used</p>
          )}
          <PhaseBar phase={model.phase} />
          <Activity model={model} />
          {model.failure && (
            <p className="callout" role="status">
              <strong>Reproduced:</strong> {model.failure.message}
            </p>
          )}
          <div className="grid">
            <AttemptTree model={model} selected={selected} onSelect={setSelected} />
            {result && (
              <Evidence
                result={result}
                candidateId={selected && selected !== "baseline" ? selected : null}
                actions={result.winner && runId ? <PullRequest key={runId} runId={runId} /> : null}
              />
            )}
          </div>
        </>
      )}
    </div>
  );
}
