"""
automation.discovery.csv_import
-------------------------------
v9.4 CSV import provider — local-only discovery from CSV files dropped
into `data/imports/`.

Workflow:
  1. User saves a CSV from anywhere (chamber roster, exported business
     list, LLM-generated list, even a manually-built spreadsheet) into
     `data/imports/`.
  2. User clicks "Find Leads For Me" with the CSV Import chip selected.
  3. This provider reads every `*.csv` in that folder, maps headers,
     filters by category + city if those columns exist, and returns
     matching rows as candidate dicts.

Header matching is flexible (case-insensitive, whitespace-tolerant)
because users will have CSVs from many sources. Common synonyms map
to the canonical candidate fields the lead engine expects.

Safety:
  - Reads ONLY from `data/imports/`. Path-traversal guarded.
  - 10 MB per file, 5,000 rows per file caps. Files larger than that
    are truncated with a warning in the message.
  - Stdlib `csv` only — no new dependencies.
  - `data/imports/` is gitignored — business lists never leave the
    local machine via git.
  - No outbound calls of any kind. Pure local file read.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path


NAME             = "csv_import"
DISPLAY_NAME     = "CSV Import"
DESCRIPTION      = (
    "Local CSV files in data/imports/. Header-tolerant — works with "
    "chamber rosters, exported business lists, hand-built spreadsheets. "
    "Filters by category + city when those columns exist."
)
REQUIRES_NETWORK = False


class CsvImportError(Exception):
    """Raised for unrecoverable CSV parse / IO errors. Per-file errors
    during discover() don't raise — they're captured in the result
    message so the user sees which file failed."""


ERROR_CLASS = CsvImportError


# Resolve once at import time; the folder is created lazily when the
# user first drops a file.
_ROOT          = Path(__file__).resolve().parents[2]
IMPORTS_DIR    = _ROOT / "data" / "imports"
MAX_FILE_BYTES = 10 * 1024 * 1024     # 10 MB / file
MAX_ROWS       = 5_000                # rows / file
MAX_CSV_FILES  = 50                   # safety cap on directory scan


# Canonical field → list of header synonyms (lowercased, whitespace-
# collapsed for matching). Keep this short and unambiguous — odd one-
# offs can be added in the future when real CSVs surface the need.
HEADER_SYNONYMS: dict[str, tuple[str, ...]] = {
    "business_name": (
        "business name", "business", "name", "company", "company name",
        "title", "business_name", "biz", "biz name",
    ),
    "phone": (
        "phone", "phone number", "phone#", "telephone", "tel", "cell",
        "mobile", "contact phone", "contact number",
    ),
    "email": (
        "email", "e-mail", "email address", "contact email", "e_mail",
    ),
    "website_url": (
        "website", "url", "web", "site", "web address", "homepage",
        "website url", "website_url",
    ),
    "city_state": (
        "city, state", "city,state", "city state", "city", "town",
        "location", "address city", "city_state",
    ),
    "category": (
        "category", "type", "business type", "industry", "vertical",
        "kind", "sector",
    ),
    "evidence_notes": (
        "notes", "description", "about", "details", "evidence_notes",
        "evidence",
    ),
    "source_url": (
        "source url", "source_url", "source", "directory", "linkedin",
        "facebook url", "fb url", "fb",
    ),
    "facebook_url": (
        "facebook", "facebook page", "fb page", "facebook_url",
    ),
    "instagram_url": (
        "instagram", "ig", "instagram_url",
    ),
}


def _norm_header(h: str) -> str:
    """Lowercase + collapse whitespace; strip enclosing quotes."""
    return " ".join((h or "").strip().strip('"').lower().split())


def _build_field_map(headers: list[str]) -> dict[str, int]:
    """
    Map canonical field → column index, using the first matching
    synonym per field. Headers we don't recognize are silently ignored.
    """
    norm = [_norm_header(h) for h in headers]
    out: dict[str, int] = {}
    for field, syns in HEADER_SYNONYMS.items():
        for syn in syns:
            if syn in norm:
                out[field] = norm.index(syn)
                break
    return out


def _list_csv_files() -> list[Path]:
    """Return CSV files in IMPORTS_DIR. Empty list if the folder
    doesn't exist (e.g. user never created it). Path-traversal-safe
    because we never let the user pass a path."""
    if not IMPORTS_DIR.is_dir():
        return []
    files: list[Path] = []
    for entry in sorted(IMPORTS_DIR.iterdir()):
        if not entry.is_file():
            continue
        if entry.suffix.lower() != ".csv":
            continue
        # Belt-and-braces: ensure the resolved path is still inside
        # IMPORTS_DIR (defends against symlink shenanigans).
        try:
            resolved = entry.resolve()
            if not str(resolved).startswith(str(IMPORTS_DIR.resolve())):
                continue
        except OSError:
            continue
        files.append(entry)
        if len(files) >= MAX_CSV_FILES:
            break
    return files


def is_available() -> bool:
    """True iff at least one .csv file exists in data/imports/."""
    return len(_list_csv_files()) > 0


def _row_matches(row_value: str, want: str) -> bool:
    """Loose substring match (case-insensitive, whitespace-tolerant).
    Returns True for empty want (no filter) or when row_value contains
    want."""
    w = (want or "").strip().lower()
    if not w:
        return True
    v = (row_value or "").strip().lower()
    return w in v or v in w


def _build_candidate(
    row: dict[str, str],
    field_map: dict[str, int],
    raw_row: list[str],
    default_category: str,
    default_city: str,
    source_file: str,
) -> dict | None:
    """
    Map a parsed row → candidate dict. Returns None if the row has no
    usable business_name (we don't queue truly empty rows). Fills in
    category + city from the discover args when the CSV doesn't carry
    those columns.
    """
    def _get(field: str) -> str:
        idx = field_map.get(field)
        if idx is None:
            return ""
        try:
            return (raw_row[idx] or "").strip()
        except IndexError:
            return ""

    name = _get("business_name")
    if not name:
        return None

    cat = _get("category") or default_category
    city = _get("city_state") or default_city

    website = _get("website_url")
    if website and not website.lower().startswith(("http://", "https://")):
        website = "https://" + website
    website_status = "has website but needs cleanup" if website else "no website found"

    fb = _get("facebook_url")
    if fb and not fb.lower().startswith(("http://", "https://")):
        fb = "https://" + fb

    ig = _get("instagram_url")
    if ig and not ig.lower().startswith(("http://", "https://")):
        ig = "https://" + ig

    source_url = _get("source_url") or fb or website

    evidence_lines = [f"Source: {source_file} (CSV import)."]
    notes = _get("evidence_notes")
    if notes:
        evidence_lines.append(notes)
    evidence_lines.append(
        "Verify contact via Google before any outreach. CSV data is as "
        "fresh as the file you imported."
    )
    evidence = " ".join(evidence_lines)

    return {
        "business_name":  name,
        "category":       cat,
        "city_state":     city,
        "website_url":    website,
        "website_status": website_status,
        "email":          _get("email"),
        "phone":          _get("phone"),
        "facebook_url":   fb,
        "instagram_url":  ig,
        "source_url":     source_url,
        "evidence_notes": evidence,
        # The chain dedup + cleaner will tag discovery_source; we also
        # set it explicitly so any direct call lands cleanly.
        "discovery_source":  "csv_import",
        # Conservative defaults — the user can flip these per-row.
        "is_local_service":  True,
        "is_active":         True,
        "is_corporate":      False,
    }


def _parse_csv_file(path: Path, default_category: str, default_city: str) -> tuple[list[dict], str, int]:
    """
    Parse a single CSV file. Returns (candidates, message, raw_row_count).
    Per-file errors are caught and surfaced via the message — they do
    NOT raise, so one bad CSV doesn't poison a multi-file import.
    """
    candidates: list[dict] = []
    raw_count = 0
    try:
        size = path.stat().st_size
        if size > MAX_FILE_BYTES:
            return [], (
                f"{path.name}: skipped (size {size} bytes > "
                f"{MAX_FILE_BYTES} cap)"
            ), 0
        # Read up to the file cap. CSV parsers accept text streams.
        with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as f:
            # Sniff dialect — handles commas, semicolons, tabs.
            head = f.read(8192)
            f.seek(0)
            try:
                dialect = csv.Sniffer().sniff(head, delimiters=",;\t|")
            except csv.Error:
                dialect = csv.excel  # plain comma
            reader = csv.reader(f, dialect)
            try:
                headers = next(reader)
            except StopIteration:
                return [], f"{path.name}: empty (no header row)", 0
            field_map = _build_field_map(headers)
            if "business_name" not in field_map:
                # No usable name column. Surface this clearly so the
                # user knows the headers didn't match.
                return [], (
                    f"{path.name}: skipped (no business name column "
                    f"found; expected one of "
                    f"{', '.join(HEADER_SYNONYMS['business_name'][:3])}…)"
                ), 0
            for i, row in enumerate(reader):
                raw_count += 1
                if i >= MAX_ROWS:
                    return candidates, (
                        f"{path.name}: truncated at {MAX_ROWS} rows "
                        f"(file had more)"
                    ), raw_count
                cand = _build_candidate(
                    row=dict(zip(headers, row)),
                    field_map=field_map,
                    raw_row=row,
                    default_category=default_category,
                    default_city=default_city,
                    source_file=path.name,
                )
                if cand is not None:
                    candidates.append(cand)
    except (OSError, csv.Error) as e:
        return candidates, f"{path.name}: read error — {e}", raw_count
    return candidates, f"{path.name}: parsed {len(candidates)} rows", raw_count


def discover(
    category: str,
    city_state: str,
    count: int,
    source: str | None = None,
    **opts,
) -> dict:
    """
    Read CSVs in data/imports/, filter by category + city when those
    columns exist, return up to `count` candidates.

    Args:
        category, city_state: search terms. Used as defaults for rows
            whose CSV doesn't carry those columns, AND as substring
            filters for rows that DO have category/city columns.
        count: max candidates to return.
        source: optional. When provided, only the named CSV file in
            `data/imports/` is read (basename only; path-traversal-
            guarded). Defaults to reading every CSV in the folder.

    Returns:
        Standard ProviderResult shape. The `message` lists per-file
        outcomes so the user knows what was read, skipped, and why.
    """
    if not isinstance(count, int) or count < 1:
        raise ValueError("count must be a positive integer")

    files = _list_csv_files()
    if source:
        # Restrict to the named file. Guard the basename.
        safe = Path(source).name  # strips any directory components
        files = [f for f in files if f.name == safe]
        if not files:
            return {
                "candidates":  [],
                "total_found": 0,
                "provider":    NAME,
                "message":     f"CSV import: no file named {safe!r} in data/imports/.",
            }
    if not files:
        return {
            "candidates":  [],
            "total_found": 0,
            "provider":    NAME,
            "message":     (
                "CSV import: data/imports/ is empty. Drop a .csv there "
                "and re-run."
            ),
        }

    cat_q = (category or "").strip()
    city_q = (city_state or "").strip()

    all_candidates: list[dict] = []
    per_file_msgs: list[str] = []
    total_raw_rows = 0

    for f in files:
        cands, msg, raw_count = _parse_csv_file(
            f, default_category=cat_q, default_city=city_q,
        )
        per_file_msgs.append(msg)
        total_raw_rows += raw_count
        # Per-file filter: if the row carried its own category/city
        # values (i.e. the CSV had those columns), enforce the user's
        # filter. Rows that inherited the default category/city from
        # discover() args are kept as-is (they trivially match).
        for cand in cands:
            # Did this row's category come from the CSV or from default?
            # If the CSV's category column was present, it'll be on the
            # row directly; we can't distinguish at this point, so we
            # apply a loose substring match either way. Loose match
            # against the default also passes trivially.
            if cat_q and not _row_matches(cand.get("category", ""), cat_q):
                continue
            if city_q and not _row_matches(cand.get("city_state", ""), city_q):
                continue
            all_candidates.append(cand)

    # Quality sort: rows with email OR phone bubble up so users see
    # the actionable ones first.
    def _quality_rank(c: dict) -> int:
        score = 0
        if (c.get("email") or "").strip():   score += 2
        if (c.get("phone") or "").strip():   score += 1
        if (c.get("website_url") or "").strip(): score += 1
        return -score  # negate for ascending sort = best first
    all_candidates.sort(key=_quality_rank)

    capped = all_candidates[:count]

    message = (
        f"CSV import: {len(capped)} of {len(all_candidates)} matching "
        f"rows from {len(files)} file{'s' if len(files) != 1 else ''}. "
        + "; ".join(per_file_msgs)
    )

    return {
        "candidates":  capped,
        "total_found": len(all_candidates),
        "provider":    NAME,
        "message":     message,
        # Passthrough extras — useful for debugging in the UI.
        "files_read":  [f.name for f in files],
        "raw_rows":    total_raw_rows,
    }
