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
    python3 automation/daily_ops.py                 # full sequence (1, 2, 3)
    python3 automation/daily_ops.py --skip-generate # skip step 1: only refresh
                                                    # snapshot + summary (no
                                                    # OpenAI, no new drafts)

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

STEPS: list[tuple] = [
    # (label, script, *args). Optional positional args are passed
    # through to the child process. The daily_report step needs
    # --yesterday so the report captures the FULL previous day rather
    # than only the hours that elapsed before the cron fired.
    ("Generate daily drafts", "automation/daily_runner.py"),
    ("Write status snapshot", "automation/status_snapshot.py"),
    ("Write morning summary", "automation/morning_summary.py"),
    ("Write daily report",    "automation/daily_report.py",   "--yesterday"),
]


def _say(*args, **kwargs) -> None:
    """print() that flushes immediately so step markers stay in order
    when stdout is piped (e.g. when launchd captures the output)."""
    print(*args, **kwargs, flush=True)


def main() -> int:
    # Tiny flag parser — only one optional flag is accepted. Any other
    # argument is a usage error and exits 2.
    skip_generate = False
    for arg in sys.argv[1:]:
        if arg == "--skip-generate":
            skip_generate = True
        else:
            _say("Usage: python3 automation/daily_ops.py [--skip-generate]")
            return 2

    _say("PartnerDeskAI Daily Ops")
    _say()

    if skip_generate:
        # Show the skipped step explicitly so the output stays readable
        # and the user knows nothing was generated this run.
        _say("[skip] Generate daily drafts")
        active_steps = STEPS[1:]
    else:
        active_steps = STEPS

    total = len(active_steps)
    for idx, step in enumerate(active_steps, start=1):
        label, script, *extra_args = step
        _say(f"[{idx}/{total}] {label}")
        result = subprocess.run(
            [sys.executable, str(ROOT / script), *extra_args],
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
