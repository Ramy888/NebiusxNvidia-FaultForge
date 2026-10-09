import { describe, expect, it } from "vitest";
import { decodedPath, isRunStart } from "../src/routes";

// What the Worker uses to decide whether a request starts a (credit-spending) run.
const startsRun = (method: string, pathname: string) => {
  const path = decodedPath(pathname);
  return path !== null && isRunStart(method, path);
};

describe("run-start detection", () => {
  it("matches the plain path", () => {
    expect(startsRun("POST", "/api/runs")).toBe(true);
  });

  it("matches percent-encoded spellings the server also routes to /api/runs", () => {
    expect(startsRun("POST", "/api/%72uns")).toBe(true);
    expect(startsRun("POST", "/api/run%73")).toBe(true);
    expect(startsRun("POST", "/%61pi/runs")).toBe(true);
  });

  it("ignores other methods and paths", () => {
    expect(startsRun("GET", "/api/runs")).toBe(false);
    expect(startsRun("POST", "/api/runs/abc/pull-request")).toBe(false);
  });

  it("rejects malformed escapes", () => {
    expect(decodedPath("/api/%E0%A4%A")).toBeNull();
  });
});
