#!/usr/bin/env python3
# clean_placeholder_titles.py
#
# Blanks "placeholder" titles in downloads.csv that look like:
#   TikTok video #7495875761379986734
# Resulting rows become:
#   Index,,URL
#
# - Works in-place by default (creates downloads.csv.bak backup)
# - Preserves column order and any extra columns (e.g., "User")
# - Robust to UTF-8 BOM, Windows newlines, commas/quotes inside fields
# - --dry-run prints what would change without writing
#
# Examples:
#   python clean_placeholder_titles.py
#   python clean_placeholder_titles.py --csv downloads.csv --dry-run
#   python clean_placeholder_titles.py --output cleaned.csv
#   python clean_placeholder_titles.py --pattern "^TikTok video #\\d+$"

import argparse
import csv
import re
import shutil
from pathlib import Path
from typing import List

DEFAULT_PATTERNS = [r"^TikTok video #\d+$"]  # case-insensitive match

def find_title_header(fieldnames: List[str]) -> str:
    """Return the exact header name used for Title (case-insensitive)."""
    for h in fieldnames:
        if h.lower().strip() == "title":
            return h
    raise ValueError("CSV must have a 'Title' column (case-insensitive).")

def process_csv(in_path: Path, out_path: Path, patterns: List[str], dry_run: bool) -> None:
    regexes = [re.compile(pat, re.IGNORECASE) for pat in patterns]

    with in_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError("CSV appears to have no header row.")
        fieldnames = list(reader.fieldnames)
        title_key = find_title_header(fieldnames)

        rows = []
        total = 0
        changed = 0

        for row in reader:
            total += 1
            title = (row.get(title_key) or "").strip()
            if title and any(rx.fullmatch(title) for rx in regexes):
                # Blank the placeholder title
                row[title_key] = ""
                changed += 1
            rows.append(row)

    if dry_run:
        print(f"[dry-run] Would update {changed} / {total} rows in {in_path}")
        return

    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"[ok] Updated {changed} / {total} rows -> {out_path}")

def main():
    ap = argparse.ArgumentParser(description="Blank placeholder TikTok titles in downloads.csv")
    ap.add_argument("--csv", default="downloads.csv", help="Path to input CSV (default: downloads.csv)")
    ap.add_argument("--output", default=None, help="Optional output CSV path (default: overwrite input)")
    ap.add_argument("--dry-run", action="store_true", help="Show what would change without writing")
    ap.add_argument("--no-backup", action="store_true", help="Do not create .bak when overwriting input")
    ap.add_argument("--pattern", action="append", default=None,
                    help="Add a placeholder-title regex (case-insensitive). "
                         "Use multiple --pattern flags to add more.")
    args = ap.parse_args()

    in_path = Path(args.csv)
    if not in_path.exists():
        raise SystemExit(f"Input CSV not found: {in_path}")

    patterns = args.pattern if args.pattern else DEFAULT_PATTERNS

    # Decide output path
    if args.output:
        out_path = Path(args.output)
    else:
        out_path = in_path

    # Backup if overwriting and not --no-backup and not --dry-run
    if out_path == in_path and not args.no_backup and not args.dry_run:
        bak = in_path.with_suffix(in_path.suffix + ".bak")
        shutil.copy2(in_path, bak)
        print(f"[backup] {bak}")

    process_csv(in_path, out_path, patterns, dry_run=args.dry_run)

if __name__ == "__main__":
    main()
