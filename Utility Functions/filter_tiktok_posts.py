#!/usr/bin/env python3
"""
Filter a list of TikTok links to keep only *post* URLs
(i.e., links that contain /video/ or /photo/ in the path).

Usage:
  python filter_tiktok_posts.py links.txt            # writes filtered_links.txt next to input
  python filter_tiktok_posts.py links.txt --in-place # overwrites links.txt in place
  python filter_tiktok_posts.py links.txt -o kept.txt

The script preserves order and formatting (one URL per line). Blank lines are removed.
"""
from __future__ import annotations
import argparse
from pathlib import Path
from urllib.parse import urlparse

def is_tiktok_post(url: str) -> bool:
    """Return True iff the URL looks like a TikTok *post* (has /video/ or /photo/ in the path)."""
    try:
        u = url.strip()
        if not u:
            return False
        parsed = urlparse(u)
        host = (parsed.netloc or "").lower()
        path = (parsed.path or "").lower()
        if "tiktok.com" not in host:
            return False
        return "/video/" in path or "/photo/" in path
    except Exception:
        return False

def main():
    ap = argparse.ArgumentParser(description="Keep only TikTok post links (containing /video/ or /photo/).")
    ap.add_argument(
    "input",
    type=Path,
    nargs="?",                 # <--- add this
    default=Path("links.txt"), # <--- and this
    help="Path to input text file (one URL per line). Defaults to links.txt if not specified."
    )
    ap.add_argument("-o", "--output", type=Path, default=None,
                    help="Path to output file. Defaults to <input dir>/filtered_<input name>.")
    ap.add_argument("--in-place", action="store_true",
                    help="Overwrite the input file in place (no separate output file).")
    args = ap.parse_args()

    if not args.input.exists():
        raise SystemExit(f"Input file not found: {args.input}")

    lines = args.input.read_text(encoding="utf-8", errors="ignore").splitlines()
    kept = [ln for ln in lines if ln.strip() and is_tiktok_post(ln)]

    if args.in_place:
        args.input.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
        print(f"Wrote {len(kept)} post link(s) back to {args.input}")
    else:
        out = args.output or args.input.with_name(f"filtered_{args.input.name}")
        out.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
        print(f"Wrote {len(kept)} post link(s) to {out}")

if __name__ == "__main__":
    main()
