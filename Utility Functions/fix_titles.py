#!/usr/bin/env python3
# fix_missing_titles.py
#
# Fill-in missing titles for files/folders in ./collection using downloads.csv
# - Videos with no title look like:  "{index}.mp4"
# - Folders with no title look like: "{index}"
# - After renaming they become:      "{index}. {sanitized_title}.mp4"  (videos)
#                                    "{index}. {sanitized_title}"      (folders)
#
# Safety:
# - Title sanitized with sanitize_filename_keep_readables (below)
# - Final component length limited to <= 199 characters (including extension for files)
# - If target exists, appends " (1)", " (2)", ... to avoid collisions
#
# Usage:
#   python fix_missing_titles.py [--root collection] [--csv downloads.csv] [--dry-run]

import argparse
import csv
import os
import re
import unicodedata
from pathlib import Path
from typing import Dict, Optional

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

VIDEO_EXTS = {".mp4"}  # adjust if needed: {".mp4", ".webm", ".mkv", ".mov"}

# Forbidden chars for filenames on common platforms (Windows superset)
FORBIDDEN = set('<>:"/\\|?*')

# Windows reserved device names (case-insensitive)
WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
}

# ---------------------------------------------------------------------------
# Your provided sanitize/trim helpers (used as-is, with constants above)
# ---------------------------------------------------------------------------

def sanitize_filename_keep_readables(name: str, max_len: Optional[int] = None) -> str:
    """Keep emojis/hashtags; only strip control chars and filesystem-forbidden.
    If max_len is None, do not truncate here (let caller handle)."""
    if name is None:
        name = ""
    s = unicodedata.normalize("NFKC", name)
    s = "".join(ch for ch in s if ch.isprintable() and ord(ch) >= 32)
    s = "".join('_' if ch in FORBIDDEN else ch for ch in s)
    s = re.sub(r'[\r\n\t]+', ' ', s)
    s = re.sub(r' {2,}', ' ', s).strip()
    # don't force "untitled" here; we want to allow truly blank names upstream
    # but we *must not* end with dot/space on Windows for actual filesystem paths
    stem = s.split('.', 1)[0] if s else ""
    if stem.upper() in WINDOWS_RESERVED:
        s += "_"
    if max_len is not None and len(s) > max_len:
        s = s[:max_len].rstrip('. ')
    return s

def trim_fs_component(prefix: str, title: str, *, limit: int = 199, reserve_ext: int = 0) -> str:
    """
    Build '<prefix>. <title>' and trim so that the final component length
    (including extension if reserve_ext>0) is <= limit.
    - reserve_ext: number of characters to reserve for extension (e.g., 4 for ".mp4")
    """
    # Compose the raw stem
    stem = f"{prefix}. {title}" if title else f"{prefix}"
    # Maximum allowed length for the component without the actual extension
    max_stem = max(1, limit - max(0, reserve_ext))
    if len(stem) <= max_stem:
        return stem.rstrip('. ')
    # Need to trim the title portion preferentially
    if title:
        # room left for title after prefix + ". "
        room_for_title = max_stem - (len(prefix) + 2)
        if room_for_title < 0:
            # Degenerate case: even prefix+". " exceeds; fall back to prefix only
            return f"{prefix}"[:max_stem].rstrip('. ')
        trimmed_title = title[:room_for_title].rstrip('. ')
        return (f"{prefix}. {trimmed_title}").rstrip('. ')
    else:
        # No title, trim prefix itself
        return f"{prefix}"[:max_stem].rstrip('. ')

# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

INDEX_ONLY_RE = re.compile(r"^\d+$")

def load_index_to_title(csv_path: Path) -> Dict[int, str]:
    """Load Index -> Title map from downloads.csv (robust to BOM and header case)."""
    mapping: Dict[int, str] = {}
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV not found: {csv_path}")
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError("CSV has no header row.")
        # Case-insensitive header access
        lower = {h.lower(): h for h in reader.fieldnames}
        idx_field = lower.get("index")
        title_field = lower.get("title")
        if not idx_field or not title_field:
            raise ValueError("CSV must have 'Index' and 'Title' headers.")
        for row in reader:
            raw_idx = (row.get(idx_field) or "").strip()
            if not raw_idx.isdigit():
                continue
            idx = int(raw_idx)
            title = (row.get(title_field) or "").strip()
            mapping[idx] = title
    return mapping

def ensure_unique_name(parent: Path, name: str, *, is_file: bool) -> Path:
    """Return a path under parent that doesn't exist, adding ' (n)' if necessary."""
    candidate = parent / name
    if not candidate.exists():
        return candidate
    if is_file:
        base, ext = os.path.splitext(name)
        n = 1
        while True:
            alt = parent / f"{base} ({n}){ext}"
            if not alt.exists():
                return alt
            n += 1
    else:
        base = name
        n = 1
        while True:
            alt = parent / f"{base} ({n})"
            if not alt.exists():
                return alt
            n += 1

def process(root: Path, csv_path: Path, dry_run: bool = False) -> None:
    idx_to_title = load_index_to_title(csv_path)

    renamed = 0
    skipped_no_title = 0
    skipped_has_title = 0
    skipped_missing_idx = 0
    errors = 0

    for entry in sorted(root.iterdir(), key=lambda p: p.name):
        try:
            # Case 1: video file with blank title => "123.mp4"
            if entry.is_file() and entry.suffix.lower() in VIDEO_EXTS and INDEX_ONLY_RE.fullmatch(entry.stem):
                idx = int(entry.stem)
                title = idx_to_title.get(idx, "").strip()
                if not title:
                    skipped_no_title += 1
                    print(f"[skip] #{idx}: no title in CSV for file {entry.name}")
                    continue

                safe_title = sanitize_filename_keep_readables(title)
                stem = trim_fs_component(str(idx), safe_title, limit=199, reserve_ext=len(entry.suffix))
                target_name = stem + entry.suffix
                if target_name == entry.name:
                    skipped_has_title += 1
                    print(f"[skip] #{idx}: already correctly named: {entry.name}")
                    continue

                target_path = ensure_unique_name(entry.parent, target_name, is_file=True)
                print(f"[file] {entry.name} -> {target_path.name}")
                if not dry_run:
                    entry.rename(target_path)
                renamed += 1
                continue

            # Case 2: folder with blank title => "123"
            if entry.is_dir() and INDEX_ONLY_RE.fullmatch(entry.name):
                idx = int(entry.name)
                title = idx_to_title.get(idx, "").strip()
                if not title:
                    skipped_no_title += 1
                    print(f"[skip] #{idx}: no title in CSV for folder {entry.name}/")
                    continue

                safe_title = sanitize_filename_keep_readables(title)
                stem = trim_fs_component(str(idx), safe_title, limit=199, reserve_ext=0)
                target_name = stem
                if target_name == entry.name:
                    skipped_has_title += 1
                    print(f"[skip] #{idx}: already correctly named: {entry.name}/")
                    continue

                target_path = ensure_unique_name(entry.parent, target_name, is_file=False)
                print(f"[dir ] {entry.name}/ -> {target_path.name}/")
                if not dry_run:
                    entry.rename(target_path)
                renamed += 1
                continue

            # Everything else: already has a title or not an index-based item
            skipped_has_title += 1

        except Exception as e:
            errors += 1
            print(f"[error] {entry.name}: {e}")

    print("\nDone.")
    print(f"Renamed: {renamed}")
    print(f"Skipped (no title in CSV): {skipped_no_title}")
    print(f"Skipped (already has title / not applicable): {skipped_has_title}")
    print(f"Errors: {errors}")

def main():
    ap = argparse.ArgumentParser(description="Fill in missing titles in 'collection' using downloads.csv")
    ap.add_argument("--root", default="collection", help="Path to collection folder (default: collection)")
    ap.add_argument("--csv", default="downloads.csv", help="Path to downloads.csv (default: downloads.csv)")
    ap.add_argument("--dry-run", action="store_true", help="Show what would change without renaming")
    args = ap.parse_args()

    root = Path(args.root)
    csv_path = Path(args.csv)

    if not root.exists() or not root.is_dir():
        raise SystemExit(f"Collection folder not found or not a directory: {root}")

    process(root, csv_path, dry_run=args.dry_run)

if __name__ == "__main__":
    main()
