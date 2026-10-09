// The server decodes percent-escapes before routing (/api/%72uns reaches /api/runs), so the
// Worker must match on the decoded path, or a live run could start without being counted.
export function decodedPath(pathname: string): string | null {
  try {
    return decodeURIComponent(pathname);
  } catch {
    return null; // malformed escape: refuse rather than guess
  }
}

export const isRunStart = (method: string, path: string) => method === "POST" && path === "/api/runs";
