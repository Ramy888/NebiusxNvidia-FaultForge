export type Outcome = "passed" | "failed" | "error" | "timed_out";

export interface ServerEvent {
  seq: number;
  type: string;
  data: Record<string, any>;
}

export interface Example {
  id: string;
  description: string;
}

export interface CheckResult {
  outcome: Outcome;
  message: string;
  duration_s: number;
  output: string;
}

export interface ScenarioResult {
  id: string;
  title: string;
  fault: string;
  test_path: string;
  test_code: string;
  baseline: CheckResult;
}

export interface CandidateResult {
  id: string;
  summary: string;
  accepted: boolean;
  rejection_reason: string;
  diff: string;
  diff_lines: number;
  fixed: string[];
  regressed: string[];
  existing_tests: CheckResult;
  scenarios: Record<string, CheckResult>;
}

export interface RunResult {
  repo: string;
  status: "repaired" | "no_repair" | "no_failure" | "broken_baseline";
  target: string | null;
  winner: string | null;
  existing_tests: CheckResult;
  scenarios: ScenarioResult[];
  candidates: CandidateResult[];
  dependency: { name: string; operation: string; call_sites: string[] } | null;
  research: { title: string; url: string }[];
  markdown: string;
}

export interface RunStatus {
  id: string;
  example: string;
  state: "queued" | "running" | "finished" | "failed";
  error: string | null;
  result: RunResult | null;
}
