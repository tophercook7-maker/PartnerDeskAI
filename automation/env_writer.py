"""
env_writer.py
-------------
Atomic update of values in a .env file. Existing keys are replaced in-
place (preserving line order and surrounding comments); new keys are
appended. Writes go to a temp file and are renamed into place so a
crash mid-write cannot corrupt .env.

Safety contract:
    - NEVER prints any value (key names + lengths only, on demand).
    - Preserves the existing file mode (so a 600 .env stays 600).
    - Creates a `.env.bak` snapshot before each write so the user can
      restore the previous version if anything looks wrong.
    - Quotes values that contain whitespace, '#', or '"' so the file
      stays parsable by python-dotenv.
    - Refuses to write anything if `dotenv_path` does not exist
      (we never create .env from scratch — that's the user's job, and
      we don't want to overwrite an unrelated file by accident).
"""

from pathlib import Path
import os
import re
import shutil
import tempfile


_KEY_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")


def _needs_quotes(value: str) -> bool:
    """True iff the value contains whitespace, '#', or '"'."""
    if not value:
        return False
    return any(c.isspace() or c in {"#", '"'} for c in value)


def _format_line(key: str, value: str) -> str:
    """Render a single KEY=VALUE line, quoting if needed."""
    if _needs_quotes(value):
        # Escape backslashes and double-quotes so the value can round-trip.
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'{key}="{escaped}"'
    return f"{key}={value}"


def update_env(dotenv_path: Path | str, updates: dict[str, str]) -> dict:
    """
    Atomically apply `updates` to the .env at `dotenv_path`.

    Returns a small dict with structural info ONLY — never values:
        {
            "path":     "<absolute path>",
            "backup":   "<absolute path to .env.bak>",
            "replaced": ["KEY1", ...],
            "added":    ["KEY2", ...],
            "lengths":  {"KEY1": 187, "KEY2": 13},   # for logging
        }

    Raises:
        FileNotFoundError if dotenv_path does not exist.
        ValueError        if any update key is not a valid env-var name.
    """
    path = Path(dotenv_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{path} does not exist; refusing to create.")

    for key in updates:
        if not _KEY_RE.fullmatch(key):
            raise ValueError(f"Refusing to write invalid env-var name: {key!r}")

    original_mode = path.stat().st_mode & 0o7777

    # Snapshot the current file to .env.bak (overwrites any previous backup).
    backup = path.with_suffix(path.suffix + ".bak")
    shutil.copy2(path, backup)

    # Read existing lines and replace any key that's in `updates`.
    existing_lines = path.read_text(encoding="utf-8").splitlines(keepends=False)
    replaced: list[str] = []
    added:    list[str] = []
    new_lines: list[str] = []
    pending = dict(updates)  # keys still to write (will become "added")

    for line in existing_lines:
        # Preserve comments + blank lines verbatim.
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            new_lines.append(line)
            continue
        # Match KEY=value (anything after = is the value, possibly quoted).
        eq = stripped.find("=")
        if eq <= 0:
            new_lines.append(line)
            continue
        key = stripped[:eq].strip()
        if key in pending:
            new_lines.append(_format_line(key, pending.pop(key)))
            replaced.append(key)
        else:
            new_lines.append(line)

    # Append any keys that weren't in the existing file.
    for key, value in pending.items():
        new_lines.append(_format_line(key, value))
        added.append(key)

    # Write to a temp file in the SAME directory (so the rename is atomic
    # on the same filesystem), then rename into place.
    fd, tmp_path = tempfile.mkstemp(
        prefix=".env.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("\n".join(new_lines))
            if new_lines and not new_lines[-1].endswith("\n"):
                f.write("\n")
        # Restore the original file mode on the new file before renaming.
        os.chmod(tmp_path, original_mode)
        os.replace(tmp_path, path)
    except Exception:
        # Clean up the temp file if anything went wrong before rename.
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    return {
        "path":     str(path),
        "backup":   str(backup),
        "replaced": replaced,
        "added":    added,
        # Lengths only — never the values themselves.
        "lengths":  {k: len(v) for k, v in updates.items()},
    }
