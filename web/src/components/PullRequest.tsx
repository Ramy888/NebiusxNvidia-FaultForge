import { useState } from "react";
import { previewPullRequest, type PullRequestPreview } from "../api";

export function PullRequest({ runId }: { runId: string }) {
  const [preview, setPreview] = useState<PullRequestPreview | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (!preview) {
    return (
      <div className="pr">
        <button
          className="secondary"
          onClick={() => previewPullRequest(runId).then(setPreview, (e: Error) => setError(e.message))}
        >
          Preview the pull request
        </button>
        {error && <p className="error">{error}</p>}
      </div>
    );
  }
  return (
    <div className="pr pr-open">
      <p className="pr-title">{preview.title}</p>
      <p className="note">
        Branch <code>{preview.branch}</code> · {preview.files.length} files · the hosted demo only
        previews; the CLI's <code>--open-pr</code> opens it on GitHub.
      </p>
      <ul className="pr-files">
        {preview.files.map((file) => (
          <li key={file}>
            <code>{file}</code>
          </li>
        ))}
      </ul>
    </div>
  );
}
