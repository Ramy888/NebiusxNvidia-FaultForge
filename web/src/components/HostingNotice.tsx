/** Shown on the recorded demo, which is served as static files (e.g. a Hugging Face Space). */
export function HostingNotice() {
  return (
    <aside className="hosting-notice" aria-label="How this demo is hosted">
      <strong>About this page:</strong> static hosting only. This page replays recorded runs and
      makes no model calls. Every NVIDIA Nemotron call in these recordings went to{" "}
      <strong>Nebius Token Factory</strong>, and every test and repair ran in{" "}
      <strong>Token Factory Sandboxes</strong>. No model is called through the host (Hugging
      Face).
    </aside>
  );
}
