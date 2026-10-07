// Records one real live run (Nemotron on Token Factory, every check in Token Factory Sandboxes) in
// headless Chrome, for the live segment of the demo video. This spends credit: about $0.08 a run.
// Start the server in live mode first:
//   FAULTFORGE_MODE=live FAULTFORGE_SANDBOX=contree uv run --extra contree --env-file .env \
//     uvicorn faultforge.api:create_app --factory --port 8093
// then: node scripts/demo-video/record-live.mjs  (writes scripts/demo-video/out-live/)
import { launch, sleep } from "./cdp.mjs";
import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const URL_ = process.env.DEMO_URL ?? "http://127.0.0.1:8093/";
const DIR = fileURLToPath(new URL("./out-live/", import.meta.url));
rmSync(DIR, { recursive: true, force: true });
mkdirSync(DIR + "frames", { recursive: true });

const W = 1440, H = 810;
const b = await launch({ width: W, height: H, scale: 4 / 3, port: 9353 });
const cues = [];
const cue = (text) => { cues.push({ at: b.mark(), text }); console.log(b.mark().toFixed(1), text); };
const hover = (x, y) => b.moveTo({ x, y });

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

// The camera follows the run as it grows; returns how the run ended.
async function followRun(maxMs) {
  const t0 = Date.now();
  let reproducedShown = false;
  while (Date.now() - t0 < maxMs) {
    if (await visible("Proposed fix") && await visible("Evidence")) return "repaired";
    if (await visible("no repair passed verification")) return "no repair";
    const tree = await bottom(".grid");
    const callout = await top(".callout", "Reproduced");
    if (tree != null && callout != null) {
      if (!reproducedShown) { cue("Reproduced"); await scrollTo(callout - 120); await sleep(2500); reproducedShown = true; continue; }
      await scrollTo(Math.max(callout - 120, tree - H + 40));
    } else {
      const feed = await bottom("[aria-live=polite]");
      if (feed != null) await scrollTo(feed - H + 60);
    }
    await sleep(900);
  }
  return "timeout";
}

await b.goto(URL_, 3000);
await b.startRec();
let outcome = "error";
try {
  cue("Live mode: Nemotron on Token Factory, Token Factory Sandboxes");
  await hover(500, 140); await sleep(3000);
  await b.click("order-service"); await sleep(1200);
  cue("Start the live run");
  await b.click("Break it and repair it"); await sleep(1500);
  await scrollToEl(".phases", "", 120, 900);
  outcome = await followRun(8 * 60_000);
  cue(`Run ended: ${outcome}`);
  if (outcome === "repaired") {
    await scrollToEl(".grid", "", 90, 2000);
    await b.click("Proposed fix"); await sleep(1500);
    await hover(420, 420); await sleep(2000);
    cue("Evidence");
    await scrollToEl(".evidence h3", "What broke", 160, 3000);
    await scrollToEl(".evidence h3", "Patch", 100, 3500);
  } else {
    await sleep(4000);
  }
} catch (error) {
  console.error("recording stopped early:", error.message);
}

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
console.log(`outcome ${outcome}, frames ${frames.length}, length ${(end - start).toFixed(1)} s`);
console.log(`cd ${DIR} && ffmpeg -f concat -safe 0 -i list.txt -vf "scale=1920:1080,format=yuv420p" -r 30 -c:v libx264 -crf 18 live.mp4`);
