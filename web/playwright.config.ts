import { defineConfig, devices } from "@playwright/test";

// Browser smoke tests for the two ways the UI ships. Neither calls a model or spends credit:
// - replay: the static build hosted on Hugging Face, with web/replays/ copied beside it as when
//   publishing;
// - scripted: the FastAPI server in demo mode (prewritten model answers, local sandbox).
const REPLAY_PORT = 4174;
const SCRIPTED_PORT = 8765;

export default defineConfig({
  testDir: "e2e",
  timeout: 120_000,
  expect: { timeout: 60_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: { ...devices["Desktop Chrome"], trace: "retain-on-failure" },
  projects: [
    {
      name: "replay",
      testMatch: "replay.spec.ts",
      use: { baseURL: `http://127.0.0.1:${REPLAY_PORT}` },
    },
    {
      name: "scripted",
      testMatch: "scripted.spec.ts",
      use: { baseURL: `http://127.0.0.1:${SCRIPTED_PORT}` },
    },
  ],
  webServer: [
    {
      command: `npm run build:replay && cp -R replays dist-replay/ && npx vite preview --outDir dist-replay --strictPort --port ${REPLAY_PORT} --host 127.0.0.1`,
      url: `http://127.0.0.1:${REPLAY_PORT}`,
      timeout: 120_000,
      reuseExistingServer: false,
    },
    {
      command: `npm run build && cd .. && FAULTFORGE_MODE=demo uv run uvicorn faultforge.api:create_app --factory --host 127.0.0.1 --port ${SCRIPTED_PORT}`,
      url: `http://127.0.0.1:${SCRIPTED_PORT}/api/info`,
      timeout: 120_000,
      reuseExistingServer: false,
    },
  ],
});
