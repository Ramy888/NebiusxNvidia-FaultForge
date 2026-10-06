import { delayFor, replayEvents } from "./replay";
import type { ServerEvent } from "./types";

test("a recording replays every event in order, numbered, then ends", () => {
  const queue: (() => void)[] = [];
  const schedule = (fn: () => void) => {
    queue.push(fn);
    return queue.length;
  };
  const seen: ServerEvent[] = [];
  let ended = false;

  replayEvents(
    [
      { type: "pipeline_started", data: { repo: "x" } },
      { type: "run_finished", data: { branch: "baseline", check: "t", outcome: "failed" } },
    ],
    (e) => seen.push(e),
    () => (ended = true),
    schedule,
  );
  while (queue.length) queue.shift()!();

  expect(seen.map((e) => [e.seq, e.type])).toEqual([
    [0, "pipeline_started"],
    [1, "run_finished"],
  ]);
  expect(ended).toBe(true);
});

test("validation runs replay instantly; preparation steps get time to be read", () => {
  expect(delayFor({ type: "run_finished", data: { branch: "validation" } })).toBe(0);
  expect(delayFor({ type: "scenario_written", data: {} })).toBeGreaterThan(
    delayFor({ type: "run_started", data: { branch: "baseline" } }),
  );
});

test("stopping a replay prevents further events", () => {
  const queue: (() => void)[] = [];
  const seen: string[] = [];
  const stop = replayEvents(
    [
      { type: "pipeline_started", data: {} },
      { type: "pipeline_finished", data: {} },
    ],
    (e) => seen.push(e.type),
    () => seen.push("end"),
    (fn) => {
      queue.push(fn);
      return queue.length;
    },
  );

  queue.shift()!();
  stop();
  while (queue.length) queue.shift()!();

  expect(seen).toEqual(["pipeline_started"]);
});
