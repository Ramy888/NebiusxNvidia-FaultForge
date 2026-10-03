export function Diff({ diff }: { diff: string }) {
  if (!diff.trim()) return <p className="note">No changes.</p>;
  return (
    <pre className="code diff" aria-label="Patch">
      {diff.split("\n").map((line, i) => {
        const kind = line.startsWith("+++") || line.startsWith("---")
          ? "file"
          : line.startsWith("@@")
            ? "hunk"
            : line.startsWith("+")
              ? "add"
              : line.startsWith("-")
                ? "del"
                : "ctx";
        return (
          <span key={i} className={`diff-${kind}`}>
            {line || " "}
            {"\n"}
          </span>
        );
      })}
    </pre>
  );
}
