// Records the silent demo video from the replay build (real recorded live runs; no model calls, no
// credit) in headless Chrome: no browser chrome or overlays, a drawn pointer, 1920x1080.
// Serve the replay build first:
//   cd web && npm run build:replay && cp -R replays dist-replay/ && npx vite preview --outDir dist-replay --port 4180
// then: node scripts/demo-video/record.mjs  (writes scripts/demo-video/out/; see the ffmpeg line it prints)
import { launch, sleep } from "./cdp.mjs";
import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const URL_ = process.env.DEMO_URL ?? "http://127.0.0.1:4180/";
const DIR = fileURLToPath(new URL("./out/", import.meta.url));
rmSync(DIR, { recursive: true, force: true });
mkdirSync(DIR + "frames", { recursive: true });

const W = 1440, H = 810;
const b = await launch({ width: W, height: H, scale: 4 / 3, port: 9352 });
const cues = [];
const cue = (text) => { cues.push({ at: b.mark(), text }); console.log(b.mark().toFixed(1), text); };
const hover = (x, y) => b.moveTo({ x, y });

// page y of the first element matching a selector, optionally containing some text
const top = (sel, text = "") => b.evaluate(`(() => {
  const e = [...document.querySelectorAll(${JSON.stringify(sel)})].find((e) => e.textContent.includes(${JSON.stringify(text)}));
  return e ? e.getBoundingClientRect().top + scrollY : null; })()`);
const bottom = (sel) => b.evaluate(`(() => { const e = document.querySelector(${JSON.stringify(sel)});
  return e ? e.getBoundingClientRect().bottom + scrollY : null; })()`);
const scrollTo = (y) => b.evaluate(`window.scrollTo({ top: ${Math.max(0, Math.round(y))}, behavior: "smooth" })`);
const scrollToEl = async (sel, text = "", offset = 90, wait = 1200) => {
  const y = await top(sel, text);
  if (y == null) throw new Error(`missing ${sel} ${text}`);
  await scrollTo(y - offset); await sleep(wait);
};
const visible = (text) => b.evaluate(`document.body.textContent.includes(${JSON.stringify(text)})`);

// The camera follows the run as it grows: the preparation feed, then the attempt tree.
async function followRun(maxMs = 90_000) {
  const t0 = Date.now();
  let reproducedShown = false;
  while (Date.now() - t0 < maxMs) {
    if (await visible("Proposed fix") && await visible("Evidence")) return;
    const tree = await bottom(".grid");
    const callout = await top(".callout", "Reproduced");
    if (tree != null && callout != null) {
      if (!reproducedShown) { await scrollTo(callout - 120); await sleep(2500); reproducedShown = true; continue; }
      await scrollTo(Math.max(callout - 120, tree - H + 40));
    } else {
      const feed = await bottom("[aria-live=polite]");
      if (feed != null) await scrollTo(feed - H + 60);
    }
    await sleep(900);
  }
  throw new Error("run did not finish");
}

async function runService(id, intro) {
  await scrollTo(0); await sleep(1200);
  cue(intro);
  await b.click(id); await sleep(1500);
  await b.click("Replay the recorded run"); await sleep(800);
  await scrollToEl(".phases", "", 120, 900);
  await followRun();
  await sleep(1500);
}

await b.goto(URL_, 3000);
await b.startRec();

// 1. What it is, and how the page is hosted
cue("FaultForge: what breaks when a dependency misbehaves");
await sleep(2500); await hover(450, 160); await sleep(2500);
cue("Static page: replays recorded live runs; every model call went to Nebius Token Factory");
await hover(480, 375); await sleep(4000);

// 2. order-service: the full story
await runService("order-service", "order-service: a shop backend that retries timed-out fulfillment calls");
cue("Reproduced: a timeout after the provider accepted the order -> two fulfillments");
await hover(360, 300); await sleep(1500);
cue("Every repair replayed against every failure, each in its own sandbox branch");
await scrollToEl(".grid", "", 90, 1800);
await b.click("Proposed fix"); await sleep(1500);
await hover(420, 420); await sleep(2500);
cue("Evidence: before -> after for every scenario");
await scrollToEl(".evidence h3", "What broke", 160, 3500);
await scrollToEl(".evidence h3", "Repair", 120, 3500);
cue("The patch: send an Idempotency-Key with the order id");
await scrollToEl(".evidence h3", "Patch", 100, 4500);
cue("Research on the real dependency (Tavily), cited");
await scrollToEl(".evidence h3", "Research", 140, 4000);

// 3. webhook-service: a rate-limited charge check read as success
await runService("webhook-service", "webhook-service: a payment webhook that checks each charge");
cue("Reproduced: a 429 from the payment provider is read as success -> unpaid order marked paid");
await hover(360, 300); await sleep(2500);
await scrollToEl(".grid", "", 90, 2500);
cue("Fix: check the response status before marking the order paid");
await scrollToEl(".evidence h3", "Patch", 100, 4500);

// 4. hook-slinger: an unchanged open-source project
await runService("hook-slinger", "hook-slinger: an unchanged open-source webhook service (rednafi/hook-slinger)");
cue("Reproduced: a duplicate delivery is processed twice");
await hover(360, 300); await sleep(2500);
await scrollToEl(".grid", "", 90, 2500);
cue("Fix: a stable idempotency key carried through the retry queue, verified in Sandboxes");
await scrollToEl(".evidence h3", "Patch", 100, 4500);
await scrollToEl(".evidence h3", "Research", 140, 3000);

// 5. Close
await scrollTo(0); await sleep(1500);
cue("FaultForge: NVIDIA Nemotron on Nebius Token Factory, Token Factory Sandboxes");
await hover(700, 120); await sleep(4000);

const { frames, end } = await b.stopRec();
b.close();

// frames -> constant 30 fps: each output slot shows the newest frame captured by then
const FPS = 30, start = frames[0].t, slots = Math.ceil((end - start) * FPS);
const list = []; let j = 0; const written = new Map();
for (let s = 0; s < slots; s++) {
  const t = start + s / FPS;
  while (j + 1 < frames.length && frames[j + 1].t <= t) j++;
  if (!written.has(j)) {
    const name = `frames/${String(j).padStart(5, "0")}.jpg`;
    writeFileSync(DIR + name, Buffer.from(frames[j].data, "base64")); written.set(j, name);
  }
  list.push(`file '${written.get(j)}'`, `duration ${(1 / FPS).toFixed(6)}`);
}
list.push(list[list.length - 2]);
writeFileSync(DIR + "list.txt", list.join("\n") + "\n");
writeFileSync(DIR + "cues.json", JSON.stringify(cues.map((c) => ({ at: Math.max(0, c.at - start), text: c.text })), null, 1));
console.log(`frames ${frames.length}, length ${(end - start).toFixed(1)} s`);
console.log(`cd ${DIR} && ffmpeg -f concat -safe 0 -i list.txt -vf "scale=1920:1080,format=yuv420p" -r 30 -c:v libx264 -crf 18 demo.mp4`);
