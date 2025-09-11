#!/usr/bin/env python3
# tt_batch_downloader.py
#
# Batch TikTok downloader for mixed videos & photo slideshows.
# - Videos via yt-dlp -> "collection/{index}. {title}.ext"
#   (if no title -> "collection/{index}.ext")
# - Photo slideshows via gallery-dl -> folder "collection/{index}. {title}"
#   with "1.jpg", "2.jpg", ... and "sound.ext"
#   (if no title -> folder "collection/{index}" on POSIX; "{index}. _" on Windows)
# - CSV log "downloads.csv": Index,Title,URL  (title blank if placeholder)
#
# Usage: python tt_batch_downloader.py [links.txt]
#
# Dependencies:
#   pip install yt-dlp gallery-dl
#   ffmpeg installed (for yt-dlp audio extraction fallback)

import csv
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import unicodedata
from pathlib import Path
from typing import List, Tuple, Optional, Union

# ----------------------------- Constants ---------------------------------

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
AUDIO_EXTS = {".m4a", ".mp3", ".aac", ".wav", ".ogg"}
VIDEO_EXTS = {".mp4", ".webm", ".mkv", ".mov"}  # used to verify video output exists

FORBIDDEN = set('<>:"/\\|?*')
WINDOWS_RESERVED = {
    'CON','PRN','AUX','NUL',
    'COM1','COM2','COM3','COM4','COM5','COM6','COM7','COM8','COM9',
    'LPT1','LPT2','LPT3','LPT4','LPT5','LPT6','LPT7','LPT8','LPT9'
}
IS_WINDOWS = platform.system().lower().startswith("win")

# ----------------------------- Utilities ---------------------------------

def wpath(p: Path) -> str:
    """Return a string path usable by Windows APIs even for >260 chars."""
    s = str(p.resolve())
    if IS_WINDOWS:
        s = s.replace("/", "\\")
        if not s.startswith("\\\\?\\"):
            s = "\\\\?\\" + s
    return s

def sanitize_filename_keep_readables(name: str, max_len: Optional[int] = None) -> str:
    """Keep emojis/hashtags; only strip control chars and filesystem-forbidden."""
    if name is None:
        name = ""
    s = unicodedata.normalize("NFKC", name)
    s = "".join(ch for ch in s if ch.isprintable() and ord(ch) >= 32)
    s = "".join('_' if ch in FORBIDDEN else ch for ch in s)
    s = re.sub(r'[\r\n\t]+', ' ', s)
    s = re.sub(r' {2,}', ' ', s).strip()
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
    """
    stem = f"{prefix}. {title}" if title else f"{prefix}"
    max_stem = max(1, limit - max(0, reserve_ext))
    if len(stem) <= max_stem:
        return stem.rstrip('. ')
    if title:
        room_for_title = max_stem - (len(prefix) + 2)
        if room_for_title < 0:
            return f"{prefix}"[:max_stem].rstrip('. ')
        trimmed_title = title[:room_for_title].rstrip('. ')
        return (f"{prefix}. {trimmed_title}").rstrip('. ')
    else:
        return f"{prefix}"[:max_stem].rstrip('. ')

def parse_input_lines(path: Path) -> List[str]:
    """
    Read links.txt. Accepts either:
      - '123. https://...' or
      - 'https://...'
    Returns a simple list of URLs in the file order (indices are ignored for incremental mode).
    """
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    idx_re = re.compile(r'^\s*(\d+)\.\s*(https?://\S+)\s*$')
    url_re = re.compile(r'^\s*(https?://\S+)\s*$')
    urls: List[str] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        m = idx_re.match(line)
        if m:
            urls.append(m.group(2))
            continue
        m = url_re.match(line)
        if m:
            urls.append(m.group(1))
    return urls

def is_slideshow(url: str) -> bool:
    """True iff path is exactly /@<username>/photo/<post_id>[/]"""
    try:
        from urllib.parse import urlparse, unquote
        path = unquote(urlparse(url).path)
        path = re.sub(r'/+$', '', path)
        segs = [s for s in path.split('/') if s]
        if len(segs) != 3:
            return False
        user, kind, post_id = segs
        return user.startswith('@') and kind == 'photo' and re.fullmatch(r'\d+', post_id) is not None
    except Exception:
        return False

def extract_post_id(url: str) -> str:
    m = re.search(r"/(\d{8,})/?$", url.split("?")[0])
    return m.group(1) if m else str(int(time.time()))

# Placeholder / no-title detection
_NO_TITLE_VIDEO_RE = re.compile(r'^\s*tiktok\s+video(?:\s*#\d+)?\s*$', re.IGNORECASE)

def is_placeholder_video_title(title: Optional[str]) -> bool:
    if not title:
        return True
    return bool(_NO_TITLE_VIDEO_RE.match(title))

def is_placeholder_slide_title(title: Optional[str], post_id: Optional[str]) -> bool:
    if not title:
        return True
    if post_id and (title.strip().lower() == f"tiktok_{post_id}" or title.strip() == post_id):
        return True
    if re.match(r'^\s*tiktok\s+photo(?:\s*#\d+)?\s*$', title, re.IGNORECASE):
        return True
    return False

def safe_blank_folder_name(index: int) -> str:
    return f"{index}. _" if IS_WINDOWS else f"{index}. "

# ------------------------- Subprocess helpers -----------------------------

def run(cmd: List[str]) -> int:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        print("[subprocess]", " ".join(cmd))
        if proc.stdout:
            print(proc.stdout)
        if proc.stderr:
            print(proc.stderr)
    return proc.returncode

def run_capture_json(cmd: List[str]) -> List[Union[dict, list, str, int, float, None]]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if proc.returncode != 0 or not proc.stdout:
            return []
        out = []
        for line in proc.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                pass
        return out
    except Exception:
        return []

# ------------------------- Title parsing helpers --------------------------

def parse_title_from_gallerydl_filename(filename: str) -> Optional[str]:
    """
    Gallery-dl default TikTok filenames look like:
      <postid>_<nn> <TITLE> [<hash>].ext
    Extract and return <TITLE>.
    """
    base = filename
    base = re.sub(r'\.[^.\\/:*?"<>|\r\n]+$', '', base)
    m = re.match(r'^\s*\d+_\d+\s+(.*?)\s+\[.*?\]\s*$', base)
    if m:
        return m.group(1).strip()
    base = re.sub(r'^\s*\d+_\d+\s*', '', base)
    base = re.sub(r'\s*\[.*?\]\s*$', '', base).strip()
    return base or None

def guess_title_from_name(name: str) -> Optional[str]:
    base = name
    if "." in base:
        base = base[:base.rfind(".")]
    base = re.sub(r"\s+\[[0-9a-fA-F]{8,}\]$", "", base)
    m = re.search(r"_(\d+)\s+(.*)$", base)
    if m:
        title = m.group(2).strip()
        title = re.sub(r"^\d{8,}\s*", "", title)
        return title if title else None
    return parse_title_from_gallerydl_filename(name)

def parse_index_from_name(name: str) -> int:
    m = re.search(r"_(\d+)\s", name)
    return int(m.group(1)) if m else 99999

# ------------------------------ Downloaders --------------------------------

def yt_dlp_info(url: str) -> dict:
    try:
        proc = subprocess.run(["yt-dlp", "-J", "--no-warnings", url],
                              capture_output=True, text=True, check=False)
        if proc.returncode == 0 and proc.stdout.strip():
            return json.loads(proc.stdout)
    except Exception:
        pass
    return {}

def download_video(index: int, url: str, title_for_fs: Optional[str], root: Path) -> Tuple[bool, str]:
    """
    Returns (success, message). Success requires yt-dlp exit 0 AND an output video file present.
    """
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    safe_title = sanitize_filename_keep_readables(title_for_fs or "", max_len=None)
    stem = trim_fs_component(str(index), safe_title, limit=199, reserve_ext=5) if safe_title else trim_fs_component(str(index), "", limit=199, reserve_ext=5)
    outtmpl = str(root / f"{stem}.%(ext)s")
    cmd = ["yt-dlp", "-o", outtmpl, url]
    print(f"[video] yt-dlp -> {outtmpl}")
    rc = run(cmd)

    # Check for any resulting video file "<stem>.<ext>" with a known video extension
    produced = list(p for p in root.glob(f"{stem}.*") if p.suffix.lower() in VIDEO_EXTS and p.is_file())
    if rc != 0 and not produced:
        return False, f"yt-dlp exit {rc}"
    if not produced:
        return False, "No output video file found"
    return True, "ok"

def process_slideshow(index: int, url: str, root: Path) -> Tuple[Path, str]:
    """
    Download slideshow -> infer title -> make final folder "index[. title]" ->
    copy images to 1..N.ext and audio to sound.ext.
    Raises Exception on failure.
    """
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    post_id = extract_post_id(url)

    tmpdir = (root / f"_t_{post_id}").resolve()
    tmpdir.mkdir(parents=True, exist_ok=True)

    cmd = [
        "gallery-dl",
        "-o", f"base-directory={str(tmpdir)}",
        "-o", "directory=.",  # flatten
        url,
    ]
    print(f"[photo] gallery-dl -> {tmpdir}")
    rc = run(cmd)
    if rc != 0:
        # Still check if it produced files; otherwise fail
        pass

    files = [p for p in tmpdir.rglob("*") if p.is_file()]
    image_files = [p for p in files if p.suffix.lower() in IMAGE_EXTS]
    audio_files = [p for p in files if p.suffix.lower() in AUDIO_EXTS]

    if not image_files:
        raise Exception("No images found; not a valid slideshow or gallery-dl failed")

    inferred_title: Optional[str] = None
    for p in sorted(image_files):
        inferred_title = guess_title_from_name(p.name)
        if inferred_title:
            break

    display_title_for_csv = ""
    if not is_placeholder_slide_title(inferred_title, post_id):
        display_title_for_csv = inferred_title or ""

    if display_title_for_csv == "":
        folder_name = trim_fs_component(str(index), "", limit=199, reserve_ext=0)
    else:
        safe_title = sanitize_filename_keep_readables(display_title_for_csv, max_len=None)
        folder_name = trim_fs_component(str(index), safe_title, limit=199, reserve_ext=0)

    final_dir = (root / folder_name).resolve()
    final_dir.mkdir(parents=True, exist_ok=True)

    image_files.sort(key=lambda p: (parse_index_from_name(p.name), p.name.lower()))
    copied = 0
    for idx, src in enumerate(image_files, start=1):
        dst = final_dir / f"{idx}{src.suffix.lower()}"
        shutil.copy2(wpath(src), wpath(dst))
        copied += 1

    if copied == 0:
        raise Exception("Downloaded slideshow had zero images after copy")

    if not audio_files:
        audio_tmpl = str((tmpdir / "extracted_audio.%(ext)s"))
        cmd = ["yt-dlp", "-x", "--audio-format", "mp3", "-o", audio_tmpl, url]
        print(f"[photo] yt-dlp (audio fallback) -> {audio_tmpl}")
        rc = run(cmd)
        # We don't hard-fail if audio extraction fails; images are the core
        files = [p for p in tmpdir.rglob("*") if p.is_file()]
        audio_files = [p for p in files if p.suffix.lower() in AUDIO_EXTS]

    if audio_files:
        audio_files.sort(key=lambda p: p.stat().st_size, reverse=True)
        a = audio_files[0]
        shutil.copy2(wpath(a), wpath(final_dir / f"sound{a.suffix.lower()}"))

    try:
        shutil.rmtree(wpath(tmpdir))
    except Exception:
        pass

    return final_dir, display_title_for_csv

# ------------------------------- Error logging -----------------------------

def append_error_row(err_csv: Path, index: int, url: str, kind: str, message: str) -> None:
    file_exists = err_csv.exists()
    with err_csv.open("a", newline="", encoding="utf-8") as ef:
        ew = csv.writer(ef, quoting=csv.QUOTE_ALL)
        if not file_exists:
            ew.writerow(["Index", "Kind", "URL", "Error"])
        ew.writerow([index, kind, url, message])

# ----------------------------- CSV helpers ---------------------------------

def load_existing_csv(csv_path: Path) -> tuple[set[int], set[str], int]:
    """
    Return (existing_indices, existing_urls, max_index).
    If CSV doesn't exist, returns (empty, empty, 0).
    """
    if not csv_path.exists():
        return set(), set(), 0

    idxs: set[int] = set()
    urls: set[str] = set()
    max_idx = 0
    with csv_path.open("r", newline="", encoding="utf-8") as f:
        r = csv.reader(f)
        header = next(r, None)
        for row in r:
            if not row:
                continue
            try:
                idx = int(row[0])
            except Exception:
                continue
            url = row[2] if len(row) > 2 else ""
            idxs.add(idx)
            if url:
                urls.add(url.strip())
            if idx > max_idx:
                max_idx = idx
    return idxs, urls, max_idx

# ------------------------------- Main --------------------------------------

def main():
    # If no filename argument given, assume "links.txt"
    if len(sys.argv) == 1:
        txt_path = Path("links.txt")
    elif len(sys.argv) == 2:
        txt_path = Path(sys.argv[1])
    else:
        print("Usage: python tt_batch_downloader.py [links.txt]")
        sys.exit(2)

    if not txt_path.exists():
        print(f"Input file not found: {txt_path}")
        sys.exit(2)

    # Read input URLs (indices in the file are ignored for incremental updates)
    input_urls = parse_input_lines(txt_path)
    print(f"[info] Found {len(input_urls)} link(s) in {txt_path}.")

    csv_path = Path("downloads.csv")
    root = Path("collection")
    root.mkdir(parents=True, exist_ok=True)

    # Load existing CSV (if any) and compute next index
    existing_indices, existing_urls, max_existing = load_existing_csv(csv_path)
    next_index = max_existing + 1 if max_existing > 0 else 1

    # Prepare CSV for appends (create with header if new)
    file_exists = csv_path.exists()
    f = csv_path.open("a", newline="", encoding="utf-8")
    w = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
    if not file_exists:
        w.writerow(["Index", "Title", "URL"])
        f.flush()
        os.fsync(f.fileno())

    errors_csv = Path("errors.csv")
    failed_indices: List[int] = []

    # Dedup within this run too
    seen_this_run: set[str] = set()

    try:
        for url in input_urls:
            url_clean = url.strip()
            if not url_clean:
                continue

            # Skip if already in CSV
            if url_clean in existing_urls:
                print(f"[skip] Already saved: {url_clean}")
                continue

            # Skip duplicates within current run
            if url_clean in seen_this_run:
                print(f"[skip] Duplicate in input: {url_clean}")
                continue
            seen_this_run.add(url_clean)

            index = next_index
            next_index += 1

            kind = "photo" if is_slideshow(url_clean) else "video"
            print(f"\n=== [{index}] {kind.upper()} ===\n{url_clean}")

            try:
                if kind == "video":
                    info = yt_dlp_info(url_clean)
                    raw_title = (info.get("title") or info.get("description") or "").strip()
                    # Blank if placeholder
                    title_for_csv = "" if is_placeholder_video_title(raw_title) else raw_title
                    title_for_fs = sanitize_filename_keep_readables(title_for_csv) if title_for_csv else ""
                    ok, msg = download_video(index, url_clean, title_for_fs, root)
                    if not ok:
                        append_error_row(errors_csv, index, url_clean, kind, msg)
                        failed_indices.append(index)
                else:
                    try:
                        final_dir, title_for_csv = process_slideshow(index, url_clean, root)
                        print(f"[photo] Saved -> {final_dir.resolve()}")
                    except Exception as e:
                        append_error_row(errors_csv, index, url_clean, kind, str(e))
                        failed_indices.append(index)
                        title_for_csv = ""  # nothing saved, keep blank

                # Append the CSV row immediately
                w.writerow([index, title_for_csv, url_clean])
                f.flush()
                os.fsync(f.fileno())
                # Track in-memory so we don't re-add in same run
                existing_urls.add(url_clean)
                existing_indices.add(index)

            except Exception as e:
                append_error_row(errors_csv, index, url_clean, kind, f"Unhandled: {e}")
                failed_indices.append(index)
                w.writerow([index, "", url_clean])
                f.flush()
                os.fsync(f.fileno())

    finally:
        f.close()
        print(f"\n[done] CSV -> {csv_path.resolve()}")
        if failed_indices:
            failed_sorted = sorted(set(failed_indices))
            print("\n[summary] Some downloads failed.")
            print("Failed indices:", ", ".join(str(i) for i in failed_sorted))
            print(f"Details saved to: {errors_csv.resolve()}")
        else:
            print("\n[summary] All new downloads completed successfully. 🎉")

if __name__ == "__main__":
    main()
