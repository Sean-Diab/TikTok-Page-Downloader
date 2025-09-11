#!/usr/bin/env python3
# build_archive.py
#
# Generates or updates archive.html (outside the collection folder) with:
# - Video cards (click to open a fit-to-screen lightbox, not fullscreen)
# - Slideshow cards with thumbnails + optional audio
# - Slideshow lightbox with ←/→ arrows + keyboard navigation + "1 of N" counter
# - Uses downloads.csv for titles
#
# Usage: python build_archive.py
# Output: ./archive.html
# Requires: ./downloads.csv and ./collection/ produced by tt_batch_downloader.py

import csv
import subprocess
import shutil
import re
import json
from pathlib import Path
from urllib.parse import quote

VIDEO_EXTS = {".mp4", ".webm", ".mkv", ".mov"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
AUDIO_NAMES = {"sound"}

ROOT = Path("collection")
THUMB_DIR = ROOT / "thumbnails"  # thumbnails saved as {index}.jpg here
CSV_PATH = Path("downloads.csv")
OUT = Path("archive.html")  # <-- outside of collection/

# ---------- CSV + path helpers ----------

def load_csv_titles(csv_path: Path):
    titles = {}
    if not csv_path.exists():
        return titles
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        for row in reader:
            if not row or len(row) < 1:
                continue
            try:
                idx = int(row[0])
            except Exception:
                continue
            title = ""
            if len(row) >= 2 and row[1]:
                title = row[1].strip().strip('"')
            titles[idx] = title
    return titles

def escape_src_inside_collection(p: Path | None) -> str | None:
    """Return URL-safe path from archive.html to the asset. Prefix with 'collection/'."""
    if p is None:
        return None
    rel_inside = p.relative_to(ROOT)
    parts = [quote(seg, safe="") for seg in rel_inside.parts]
    return "collection/" + "/".join(parts)

# ---------- discovery of assets by index ----------

def list_images(dirpath: Path):
    try:
        files = [p for p in dirpath.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS]
    except FileNotFoundError:
        return []
    def key(p: Path):
        name = p.stem
        try:
            return (int(name.split()[0].split("_")[0]), name.lower())
        except Exception:
            try:
                return (int(name), name.lower())
            except Exception:
                return (10_000_000, name.lower())
    files.sort(key=key)
    return files

def find_audio(dirpath: Path):
    if not dirpath or not dirpath.exists():
        return None
    for p in dirpath.iterdir():
        if p.is_file() and p.stem.lower() in AUDIO_NAMES:
            return p
    return None

def find_slideshow_dir_for_index(idx: int) -> Path | None:
    """Slideshow directory is either exactly '{idx}' or starts with '{idx}.'."""
    dot_prefix = f"{idx}."
    exact = ROOT / str(idx)
    if exact.exists() and exact.is_dir():
        return exact
    for p in ROOT.iterdir():
        if p.is_dir() and p.name.startswith(dot_prefix):
            return p
    return None

def find_video_for_index(idx: int) -> Path | None:
    """Video filename must start with '{idx}.' and have a known video extension."""
    dot_prefix = f"{idx}."
    for p in ROOT.iterdir():
        if p.is_file() and p.name.startswith(dot_prefix) and p.suffix.lower() in VIDEO_EXTS:
            return p
    return None

def get_or_create_video_thumbnail(idx: int, video_path: Path) -> Path | None:
    THUMB_DIR.mkdir(exist_ok=True)
    thumb_path = THUMB_DIR / f"{idx}.jpg"
    if thumb_path.exists():
        return thumb_path
    print(f"  > Generating thumbnail for #{idx} ({video_path.name})...")
    try:
        cmd = [
            "ffmpeg", "-ss", "00:00:01", "-i", str(video_path),
            "-vframes", "1", "-q:v", "3", "-hide_banner", "-loglevel", "error",
            str(thumb_path),
        ]
        subprocess.run(cmd, check=True)
        return thumb_path
    except (subprocess.CalledProcessError, FileNotFoundError):
        try:
            cmd = [
                "ffmpeg", "-ss", "00:00:00", "-i", str(video_path),
                "-vframes", "1", "-q:v", "3", "-hide_banner", "-loglevel", "error",
                str(thumb_path),
            ]
            subprocess.run(cmd, check=True)
            return thumb_path
        except Exception as e:
            print(f"    [!] Failed to generate thumbnail for #{idx}: {e}")
            return None

def infer_title_from_dirname(idx: int, dirname: str) -> str:
    prefix = f"{idx}. "
    if dirname.startswith(prefix):
        return dirname[len(prefix):].strip()
    return ""

# ---------- build item list ----------

def build_items():
    titles = load_csv_titles(CSV_PATH)

    # Build an ordered set of indices: from CSV + anything we discover
    order = set(titles.keys())
    if ROOT.exists():
        for p in ROOT.iterdir():
            m = re.match(r"^(\d+)", p.name)
            if m:
                try:
                    order.add(int(m.group(1)))
                except ValueError:
                    pass
    order = sorted(order)

    items = []
    for idx in order:
        title = titles.get(idx, "")

        slide_dir = find_slideshow_dir_for_index(idx)
        if slide_dir:
            imgs = list_images(slide_dir)
            audio = find_audio(slide_dir)
            if not title:
                title = infer_title_from_dirname(idx, slide_dir.name)
            items.append({
                "type": "slideshow",
                "index": idx,
                "title": title,
                "images": [escape_src_inside_collection(p) for p in imgs],
                "audio": escape_src_inside_collection(audio) if audio else None,
                "cover": escape_src_inside_collection(imgs[0]) if imgs else None,
            })
            continue

        video = find_video_for_index(idx)
        if video and video.exists():
            thumb = get_or_create_video_thumbnail(idx, video)
            items.append({
                "type": "video",
                "index": idx,
                "title": title,
                "src": escape_src_inside_collection(video),
                "thumbnail": escape_src_inside_collection(thumb) if thumb else None,
            })
        else:
            # Not found on disk (could be a failed download); skip but warn.
            print(f"[warn] No slideshow or video found for index {idx}")
    return items

# ---------- rendering ----------

def render_item_card(item: dict) -> str:
    idx = item["index"]
    title = (item.get("title") or "") \
        .replace("&", "&amp;") \
        .replace("<", "&lt;") \
        .replace(">", "&gt;") \
        .replace('"', "&quot;")

    badge = "VIDEO" if item["type"] == "video" else "SLIDESHOW"
    meta = f"<span class='badge'>{badge}</span><span>#{idx}</span>"
    title_html = f"<div class='title'>{title}</div>" if title else ""

    if item["type"] == "video":
        src = item["src"]
        thumbnail = item.get("thumbnail")
        media_html = (
            f'<img src="{thumbnail}" alt="Thumbnail for {title}" loading="lazy">'
            if thumbnail else
            f'<video src="{src}" preload="metadata" muted playsinline></video>'
        )
        return f"""
      <article class="card" data-type="video">
        <div class="media" data-lightbox-src="{src}" role="button" title="Click to enlarge">
          {media_html}
        </div>
        <div class="body">
          {title_html}
          <div class="meta">{meta}</div>
        </div>
      </article>
"""
    else:
        imgs = item["images"]
        cover = item.get("cover")
        audio = item.get("audio")
        imgs_json = json.dumps(imgs).replace('"', "&quot;")
        audio_attr = (audio or "")
        thumbs = "".join(
            f'<img src="{img}" loading="lazy" alt="" data-idx="{i}">'
            for i, img in enumerate(imgs)
        )
        audio_html = f'<audio controls preload="metadata" src="{audio}"></audio>' if audio else ""
        media_html = f'<img src="{cover}" alt="" data-idx="0">' if cover else "<div style='color:var(--muted)'>No images</div>"
        return f"""
      <article class="card" data-type="slideshow" data-images="{imgs_json}" data-audio="{audio_attr}">
        <div class="media" role="button" title="Click to view slideshow">
          {media_html}
        </div>
        <div class="body">
          {title_html}
          <div class="meta">{meta} • {len(imgs)} photo(s){' • audio' if audio else ''}</div>
        </div>
        <details class="gallery">
          <summary>Show all photos</summary>
          <div class="thumbs">
            {thumbs}
          </div>
          {audio_html}
        </details>
      </article>
"""

def render_grid(items) -> str:
    return "\n".join(render_item_card(it) for it in items)

def full_document(items, grid_html: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>TikTok Archive</title>
<style>
  :root {{
    --bg: #0b0b0c;
    --card: #141417;
    --muted: #9aa0a6;
    --text: #e8eaed;
    --accent: #5e9cff;
    --chip: #1f2937;
    --chip-text: #cbd5e1;
    --border: #2a2b31;
  }}
  html, body {{ margin:0; padding:0; background:var(--bg); color:var(--text); font-family: system-ui, -apple-system, Segoe UI, Roboto, Inter, Arial, sans-serif; }}
  header {{
    position: sticky; top: 0; z-index: 10;
    background: linear-gradient(180deg, rgba(11,11,12,0.95) 0%, rgba(11,11,12,0.75) 100%);
    backdrop-filter: blur(8px);
    border-bottom: 1px solid var(--border);
  }}
  .wrap {{ max-width: 1440px; margin: 0 auto; padding: 16px 20px; }}
  h1 {{ margin: 0; font-size: 20px; letter-spacing: 0.2px; }}
  .muted {{ color: var(--muted); font-size: 14px; }}
  .filters {{ display:flex; gap:8px; align-items:center; margin-top: 10px; flex-wrap: wrap; }}
  .chip {{
    border: 1px solid var(--border); background: var(--chip); color: var(--chip-text);
    padding: 6px 10px; border-radius: 999px; font-size: 12px; cursor: pointer; user-select: none;
  }}
  .chip.active {{ outline: 2px solid var(--accent); color: white; }}

  main .grid {{
    display: grid; grid-template-columns: repeat(auto-fill, minmax(420px, 1fr));
    gap: 16px; padding: 16px 20px 60px; max-width: 1440px; margin: 0 auto;
  }}
  .card {{
    background: var(--card); border: 1px solid var(--border); border-radius: 16px;
    overflow: hidden; display:flex; flex-direction: column;
    box-shadow: 0 0 0 1px rgba(255,255,255,0.02), 0 12px 30px rgba(0,0,0,0.35);
  }}
  .media {{
    aspect-ratio: 16 / 9;
    background: #0f1115; display:flex; align-items:center; justify-content:center;
    cursor: pointer;
  }}
  video, img {{ max-width: 100%; max-height: 100%; width: 100%; height: 100%; object-fit: contain; display:block; }}
  .body {{ padding: 12px 14px 14px; display:flex; flex-direction: column; gap: 10px; }}
  .title {{ font-size: 14px; line-height: 1.35; }}
  .meta {{ display:flex; gap:8px; align-items:center; color: var(--muted); font-size: 12px; }}
  .badge {{ background: #0e1a33; color: #9ec1ff; padding: 2px 8px; border-radius: 999px; font-weight: 600; letter-spacing: 0.3px; border: 1px solid #24365a; }}
  details.gallery {{ border-top: 1px solid var(--border); padding: 12px 14px; }}
  details.gallery summary {{ cursor: pointer; color: var(--muted); outline: none; }}
  .thumbs {{ margin-top: 10px; display:grid; grid-template-columns: repeat(auto-fill, minmax(80px, 1fr)); gap: 8px; }}
  .thumbs img {{ width: 100%; height: 72px; object-fit: cover; border-radius: 8px; border: 1px solid var(--border); cursor: pointer; }}
  audio {{ width: 100%; margin-top: 10px; }}
  footer {{ color: var(--muted); font-size: 12px; text-align: center; padding: 24px; }}

  /* Lightbox overlay (not fullscreen API) */
  .lightbox {{
    position: fixed; inset: 0; z-index: 9999;
    background: rgba(0,0,0,0.8);
    display: flex; align-items: center; justify-content: center;
    padding: 24px;
  }}
  .lightbox-content {{
    position: relative;
    max-width: 90vw; max-height: 90vh;
    width: min(1200px, 90vw);
    border-radius: 12px; overflow: hidden;
    box-shadow: 0 10px 40px rgba(0,0,0,0.6), 0 0 0 1px rgba(255,255,255,0.08) inset;
    background: #0b0b0c;
  }}
  .lightbox video, .lightbox-img {{
    width: 100%; max-height: 80vh; object-fit: contain; display: block; background:#0b0b0c;
  }}
  .lightbox-audio {{
    width: 100%; display:block; background:#0b0b0c; padding: 8px 8px 12px;
  }}
  .lightbox-hint {{
    position: absolute; bottom: 8px; left: 0; right: 0; text-align: center;
    color: #cbd5e1; font-size: 12px; pointer-events: none; padding-bottom: 2px;
  }}
  .lightbox-count {{
    position: absolute; top: 8px; left: 0; right: 0; text-align: center;
    color: #e8eaed; font-size: 13px; font-weight: 600; text-shadow: 0 1px 2px rgba(0,0,0,0.6);
    pointer-events: none; padding-top: 4px;
  }}
  .nav-btn {{
    position: absolute; top: 50%; transform: translateY(-50%);
    background: rgba(0,0,0,0.45); border: 1px solid rgba(255,255,255,0.2);
    color: #fff; width: 44px; height: 64px; border-radius: 10px;
    display:flex; align-items:center; justify-content:center; cursor: pointer;
    font-size: 22px; user-select:none;
  }}
  .nav-btn:hover {{ background: rgba(0,0,0,0.6); }}
  .nav-prev {{ left: 8px; }}
  .nav-next {{ right: 8px; }}
</style>
</head>
<body>
<header>
  <div class="wrap">
    <h1>TikTok Archive</h1>
    <div class="muted">{len(items)} item(s) • folder: <code>collection/</code></div>
    <div class="filters">
      <div class="chip active" data-filter="all">All</div>
      <div class="chip" data-filter="video">Videos</div>
      <div class="chip" data-filter="slideshow">Slideshows</div>
    </div>
  </div>
</header>

<main>
  <div class="grid" id="grid">
    <!-- BEGIN GRID -->
{grid_html}
    <!-- END GRID -->
  </div>
</main>

<footer>
  Generated by <code>build_archive.py</code>. Click a video or slideshow to enlarge. Use ←/→ to navigate, and Esc or click outside to close.
</footer>

<script>
  // Filtering
  const chips = document.querySelectorAll('.chip');
  function applyFilter(kind) {{
    const cards = document.querySelectorAll('.card');
    cards.forEach(card => {{
      const t = card.dataset.type;
      card.style.display = (kind === 'all' || kind === t) ? '' : 'none';
    }});
  }}
  chips.forEach(ch => {{
    ch.addEventListener('click', () => {{
      chips.forEach(c => c.classList.remove('active'));
      ch.classList.add('active');
      applyFilter(ch.dataset.filter);
    }});
  }});

  // ---------------- Lightbox for VIDEO ----------------
  function openVideoLightbox(src) {{
    const overlay = document.createElement('div');
    overlay.className = 'lightbox';
    overlay.innerHTML = `
      <div class="lightbox-content">
        <video src="${{src}}" controls autoplay playsinline></video>
        <div class="lightbox-hint">Click outside or press ESC to close</div>
      </div>
    `;
    function close() {{
      const vid = overlay.querySelector('video');
      if (vid) try {{ vid.pause(); }} catch (e) {{}}
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = '';
      overlay.remove();
    }}
    function onKey(e) {{
      if (e.key === 'Escape') close();
    }}
    overlay.addEventListener('click', (e) => {{
      if (e.target === overlay) close();
    }});
    document.addEventListener('keydown', onKey);
    document.body.style.overflow = 'hidden';
    document.body.appendChild(overlay);
  }}

  document.querySelectorAll('.media[data-lightbox-src]').forEach(el => {{
    el.addEventListener('click', () => openVideoLightbox(el.dataset.lightboxSrc));
  }});

  // ---------------- Lightbox for SLIDESHOW ----------------
  function openImageLightbox(images, startIdx = 0, audioSrc = null) {{
    let idx = Math.max(0, Math.min(startIdx, images.length - 1));
    const overlay = document.createElement('div');
    overlay.className = 'lightbox';

    const audioHTML = audioSrc ? `<audio class="lightbox-audio" controls src="${{audioSrc}}" autoplay></audio>` : '';

    overlay.innerHTML = `
      <div class="lightbox-content" role="dialog" aria-modal="true">
        <button class="nav-btn nav-prev" aria-label="Previous">⟨</button>
        <div class="lightbox-count"></div>
        <img class="lightbox-img" alt="">
        <button class="nav-btn nav-next" aria-label="Next">⟩</button>
        ${{audioHTML}}
        <div class="lightbox-hint">Use ← / → to navigate • Click outside or press ESC to close</div>
      </div>
    `;

    const imgEl = overlay.querySelector('.lightbox-img');
    const prevBtn = overlay.querySelector('.nav-prev');
    const nextBtn = overlay.querySelector('.nav-next');
    const countEl = overlay.querySelector('.lightbox-count');

    function show(i) {{
      idx = i;
      imgEl.src = images[idx];
      prevBtn.style.visibility = (idx > 0) ? 'visible' : 'hidden';
      nextBtn.style.visibility = (idx < images.length - 1) ? 'visible' : 'hidden';
      if (countEl) countEl.textContent = `${{idx+1}} of ${{images.length}}`;
    }}

    function close() {{
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = '';
      overlay.remove();
    }}

    function onKey(e) {{
      if (e.key === 'Escape') close();
      else if (e.key === 'ArrowLeft' && idx > 0) show(idx - 1);
      else if (e.key === 'ArrowRight' && idx < images.length - 1) show(idx + 1);
    }}

    prevBtn.addEventListener('click', (e) => {{ e.stopPropagation(); if (idx > 0) show(idx - 1); }});
    nextBtn.addEventListener('click', (e) => {{ e.stopPropagation(); if (idx < images.length - 1) show(idx + 1); }});

    // Basic swipe support
    let touchX = null;
    imgEl.addEventListener('touchstart', (e) => {{ touchX = e.changedTouches[0].clientX; }});
    imgEl.addEventListener('touchend', (e) => {{
      if (touchX === null) return;
      const dx = e.changedTouches[0].clientX - touchX;
      if (dx > 40 && idx > 0) show(idx - 1);
      if (dx < -40 && idx < images.length - 1) show(idx + 1);
      touchX = null;
    }});

    overlay.addEventListener('click', (e) => {{
      if (e.target === overlay) close();
    }});

    document.addEventListener('keydown', onKey);
    document.body.style.overflow = 'hidden';
    document.body.appendChild(overlay);
    show(idx);
  }}

  // Click cover image on slideshow
  document.querySelectorAll('.card[data-type="slideshow"] .media').forEach(media => {{
    media.addEventListener('click', (e) => {{
      const card = media.closest('.card[data-type="slideshow"]');
      if (!card) return;
      const images = JSON.parse((card.dataset.images || '[]').replaceAll('&quot;', '"'));
      const audio = card.dataset.audio || null;
      let startIdx = 0;
      const img = e.target.closest('img[data-idx]');
      if (img) {{
        const n = parseInt(img.dataset.idx, 10);
        if (!Number.isNaN(n)) startIdx = n;
      }}
      if (images.length) openImageLightbox(images, startIdx, audio);
    }});
  }});

  // Click any thumbnail to open at that index
  document.querySelectorAll('.card[data-type="slideshow"] .thumbs img[data-idx]').forEach(thumb => {{
    thumb.addEventListener('click', (e) => {{
      const card = thumb.closest('.card[data-type="slideshow"]');
      if (!card) return;
      const images = JSON.parse((card.dataset.images || '[]').replaceAll('&quot;', '"'));
      const audio = card.dataset.audio || null;
      const startIdx = parseInt(thumb.dataset.idx, 10) || 0;
      if (images.length) openImageLightbox(images, startIdx, audio);
    }});
  }});
</script>
</body>
</html>
"""

# ---------- update-or-write logic ----------

GRID_BEGIN = "<!-- BEGIN GRID -->"
GRID_END = "<!-- END GRID -->"

def update_existing_html(old_html: str, grid_html: str, item_count: int) -> str | None:
    """Return updated HTML if markers are found; None if we should rewrite fresh."""
    # Replace grid
    pattern = re.compile(
        re.escape(GRID_BEGIN) + r".*?" + re.escape(GRID_END),
        flags=re.DOTALL
    )
    if not pattern.search(old_html):
        return None  # no markers -> rewrite
    new_grid_block = f"{GRID_BEGIN}\n{grid_html}\n    {GRID_END}"
    updated = pattern.sub(new_grid_block, old_html)

    # Update the item count text in header: '<div class="muted">N item(s) • ...</div>'
    updated = re.sub(
        r'(\b)\d+\s+item\(s\)',
        f"\\g<1>{item_count} item(s)",
        updated,
        count=1
    )
    return updated

def write_html(items):
    OUT.parent.mkdir(parents=True, exist_ok=True)
    grid_html = render_grid(items)

    if OUT.exists():
        try:
            old = OUT.read_text(encoding="utf-8")
        except Exception:
            old = ""
        patched = update_existing_html(old, grid_html, len(items))
        if patched is not None:
            OUT.write_text(patched, encoding="utf-8")
            print(f"[ok] Updated existing {OUT.resolve()} (grid + count).")
            return

    # Fresh full document
    html = full_document(items, grid_html)
    OUT.write_text(html, encoding="utf-8")
    print(f"[ok] Wrote {OUT.resolve()}")

# ---------- main ----------

if __name__ == "__main__":
    if not shutil.which("ffmpeg"):
        print("[error] FFmpeg is not installed or not in your PATH.")
        print("         Please install it to generate video thumbnails: https://ffmpeg.org/download.html")
        exit(1)

    items = build_items()
    write_html(items)
