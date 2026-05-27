"""
daily_ops.py
------------
Run the daily PartnerDeskAI operations sequence:

    1. Generate today's drafts (daily_runner.py)
    2. Write a status snapshot   (status_snapshot.py)
    3. Write the morning summary (morning_summary.py)

Each step is a subprocess of the corresponding standalone CLI, so this
orchestrator never touches their internals. If any step exits non-zero,
we print `[FAIL] <step>` and stop — later steps do NOT run.

Usage:
    python3 automation/daily_ops.py

Allowed writes (delegated to the underlying scripts):
    - daily_posts/YYYY-MM-DD/*.md + _raw_response.txt (daily_runner)
    - posts / post_history rows                       (daily_runner)
    - status_history/YYYY-MM-DD.json                  (status_snapshot)
    - summaries/YYYY-MM-DD.md                         (morning_summary)
    - logs/YYYY-MM-DD.log                             (daily_runner)
    - usage counters in topic/CTA/offer/hashtag banks (daily_runner)

This script does not auto-post, never approves or rejects drafts, and
makes no OpenAI call of its own (only daily_runner.py does).
"""

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent

STEPS: list[tuple[str, str]] = [
    ("Generate daily drafts", "automation/daily_runner.py"),
    ("Write status snapshot", "automation/status_snapshot.py"),
    ("Write morning summary", "automation/morning_summary.py"),
]


def _say(*args, **kwargs) -> None:
    """print() that flushes immediately so step markers stay in order
    when stdout is piped (e.g. when launchd captures the output)."""
    print(*args, **kwargs, flush=True)


def main() -> int:
    _say("PartnerDeskAI Daily Ops")
    _say()

    total = len(STEPS)
    for idx, (label, script) in enumerate(STEPS, start=1):
        _say(f"[{idx}/{total}] {label}")
        result = subprocess.run(
            [sys.executable, str(ROOT / script)],
            cwd=ROOT,
        )
        if result.returncode != 0:
            _say()
            _say(f"[FAIL] {label}")
            return result.returncode
        _say()

    _say("Daily ops complete.")
    _say("Next: python3 automation/daily_checklist.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
