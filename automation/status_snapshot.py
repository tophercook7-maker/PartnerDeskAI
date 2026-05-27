"""
status_snapshot.py
------------------
Write a daily JSON snapshot of status._gather_status() to
status_history/YYYY-MM-DD.json so trends can be diffed across days
later.

Usage:
    python3 automation/status_snapshot.py

Single intentional side effect: writes (or overwrites) today's
status_history/YYYY-MM-DD.json. Never calls OpenAI, never modifies
the database, never modifies memory banks.
"""

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import status as status_mod


ROOT = Path(__file__).resolve().parent.parent
HISTORY_DIR = ROOT / "status_history"


def main() -> int:
    data = status_mod._gather_status()
    # New top-level field. Other CLIs consuming status.py --json keep their
    # contract; this only appears in the on-disk snapshot.
    data["snapshot_created_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")

    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    path = HISTORY_DIR / f"{today}.json"
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    print(f"Wrote {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
