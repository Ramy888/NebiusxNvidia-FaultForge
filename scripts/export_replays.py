"""Turn dumps of real live runs (`faultforge run ... --dump`) into replay files for the static demo.

Usage: uv run python scripts/export_replays.py <recordings.json>
where recordings.json lists {"id", "description", "recorded", "dump"} entries.
Writes web/replays/<id>.json and web/replays/index.json.
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "web" / "replays"
DESCRIPTION = (
    "Recorded live runs: NVIDIA Nemotron 3 Ultra and Nano on Nebius Token Factory, "
    "Token Factory Sandboxes"
)
# Anything that looks like a credential must never reach a public file.
SECRET = re.compile(r"tvly-[A-Za-z0-9-]{10,}|hf_[A-Za-z0-9]{20,}|eyJ[A-Za-z0-9_-]{20,}\.")


def export(manifest: Path) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    entries = json.loads(manifest.read_text())
    index = {"description": DESCRIPTION, "recordings": []}
    for entry in entries:
        dump = json.loads(Path(entry["dump"]).read_text())
        if dump.get("result") is None:
            raise SystemExit(f"{entry['id']}: the dump has no result")
        recording = {
            "id": entry["id"],
            "description": entry["description"],
            "recorded": entry["recorded"],
            "result": dump["result"],
            "events": dump["events"],
        }
        text = json.dumps(recording, indent=1, default=str)
        if SECRET.search(text):
            raise SystemExit(f"{entry['id']}: refusing to export, it contains a credential")
        (OUT / f"{entry['id']}.json").write_text(text + "\n")
        index["recordings"].append(
            {
                "id": entry["id"],
                "description": f"{entry['description']} (recorded {entry['recorded']})",
                "file": f"{entry['id']}.json",
            }
        )
        print(f"exported {entry['id']}: {dump['result']['status']}, {len(dump['events'])} events")
    (OUT / "index.json").write_text(json.dumps(index, indent=1) + "\n")


if __name__ == "__main__":
    export(Path(sys.argv[1]))
