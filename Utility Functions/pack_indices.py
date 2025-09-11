#!/usr/bin/env python3
import csv
import re
import shutil
import sys
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parent
COLL = ROOT / "collection"
CSV_PATH = ROOT / "downloads.csv"
CSV_BACKUP = ROOT / "downloads.csv.bak"

# Patterns we'll accept for extracting the leading index
#  12. Title.ext   -> idx=12, rest=". Title.ext"
#  12 Title.ext    -> idx=12, rest=" Title.ext"
#  12.ext          -> idx=12, rest=".ext"
#  12              -> idx=12, rest=""
IDX_PATTERNS = [
    re.compile(r"^\s*(\d+)(\.\s+.*)$"),   # "12. Title..."
    re.compile(r"^\s*(\d+)(\s+.*)$"),     # "12 Title..."
    re.compile(r"^\s*(\d+)(\.\w+)$"),     # "12.mp4"
    re.compile(r"^\s*(\d+)\s*$"),         # "12"
]

def parse_index(name: str):
    """
    Return (index:int, rest:str) or (None, None) if no leading index found.
    'rest' is the remaining suffix starting at the character immediately after the index.
    """
    for pat in IDX_PATTERNS:
        m = pat.match(name)
        if m:
            idx = int(m.group(1))
            rest = m.group(2) if m.lastindex and len(m.groups()) >= 2 else ""
            return idx, rest
    return None, None

def list_items(collection_dir: Path):
    """
    Return a dict: old_index -> Path
    Assumes unique indices (one item per index).
    Ignores items that don't start with a numeric index.
    """
    index_to_path = {}
    for p in sorted(collection_dir.iterdir(), key=lambda x: x.name.lower()):
        if not p.exists():
            continue
        idx, _ = parse_index(p.name)
        if idx is None:
            # Skip items without a leading index
            continue
        if idx in index_to_path:
            print(f"[warn] Duplicate index {idx} for {p} (existing: {index_to_path[idx]}). Keeping the first, skipping this.")
            continue
        index_to_path[idx] = p
    return index_to_path

def compute_new_indices(index_to_path: dict):
    """
    Given existing indices, compute mapping old_index -> new_index (1..N without gaps) by ascending old_index.
    """
    old_indices = sorted(index_to_path.keys())
    mapping = {}
    for new_i, old_i in enumerate(old_indices, start=1):
        mapping[old_i] = new_i
    return mapping

def build_final_name(path: Path, new_index: int):
    """
    Construct the final filename for an item given its new index, preserving any title/extension.
    Rules:
      - If it was '12. Title.ext' -> 'NEW. Title.ext'
      - If '12 Title.ext' -> 'NEW Title.ext'
      - If '12.ext' -> 'NEW.ext'
      - If folder '12' -> 'NEW'
    """
    old_name = path.name
    idx, rest = parse_index(old_name)
    assert idx is not None, f"Unexpected name without index: {old_name}"

    # Normalize spacing after '.' if present like ".Title" -> ". Title"
    # Only if rest starts with "." and next is not space and not extension-only case (.ext)
    # We'll keep rest as-is to avoid surprising changes.
    new_name = f"{new_index}{rest}"
    return path.with_name(new_name)

def two_phase_renames(mapping, index_to_path):
    """
    Perform renames via a temp phase to avoid collisions, using short temp names
    to stay under Windows MAX_PATH limits.

      1) old -> __t__<uuid>_<oldidx><.ext?>   (directories have no ext)
      2) tmp -> final
    """
    from uuid import uuid4

    tmp_tag = f"__t__{uuid4().hex[:8]}_"  # short tag

    moved = []  # list of (tmp_path, final_path)
    # Phase 1: to short temp names (avoid long paths)
    for old_idx, p in sorted(index_to_path.items()):
        new_idx = mapping[old_idx]
        final_path = build_final_name(p, new_idx)

        # Short temp name in the SAME directory
        if p.is_file():
            tmp_name = f"{tmp_tag}{old_idx}{p.suffix}"
        else:
            tmp_name = f"{tmp_tag}{old_idx}"

        tmp_path = p.with_name(tmp_name)

        # Ensure parent exists
        final_path.parent.mkdir(parents=True, exist_ok=True)

        # If a leftover temp exists (crash, prior run), uniquify
        if tmp_path.exists():
            tmp_path = p.with_name(f"{tmp_tag}{old_idx}_{uuid4().hex[:4]}{p.suffix if p.is_file() else ''}")

        p.rename(tmp_path)
        moved.append((tmp_path, final_path))

    # Phase 2: temp -> final
    for tmp_path, final_path in moved:
        if final_path.exists():
            # Extremely rare: name collision; append a small suffix
            if final_path.is_file():
                final_path = final_path.with_name(
                    f"{final_path.stem}__conflict__{uuid4().hex[:6]}{final_path.suffix}"
                )
            else:
                final_path = final_path.with_name(
                    f"{final_path.name}__conflict__{uuid4().hex[:6]}"
                )
        tmp_path.rename(final_path)

    changes = []
    for tmp_path, final_path in moved:
        old_name = tmp_path.name
        new_name = final_path.name
        changes.append((old_name, new_name))
    return changes

def load_csv(csv_path: Path):
    if not csv_path.exists():
        return []
    rows = []
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        r = csv.reader(f)
        header = next(r, None)
        if header is None:
            return []
        # Normalize header positions
        # Expect "Index,Title,URL"
        for row in r:
            if not row:
                continue
            rows.append(row)
    return rows

def write_csv(csv_path: Path, rows):
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Index", "Title", "URL"])
        for row in rows:
            w.writerow(row)

def sync_csv_to_mapping(csv_rows, index_mapping, existing_old_indices_set):
    kept = []
    row_changes = []
    removed_rows = []
    for row in csv_rows:
        try:
            old_idx = int(row[0])
        except Exception:
            continue
        if old_idx not in existing_old_indices_set:
            removed_rows.append(row)
            continue
        new_idx = index_mapping[old_idx]
        new_row = [str(new_idx), row[1], row[2] if len(row) > 2 else ""]
        kept.append(new_row)
        if new_idx != old_idx:
            row_changes.append((old_idx, new_idx, row[1]))

    kept.sort(key=lambda r: int(r[0]))
    for i, row in enumerate(kept, start=1):
        row[0] = str(i)
    return kept, row_changes, removed_rows

def main():
    if not COLL.exists() or not COLL.is_dir():
        print(f"[error] Folder not found: {COLL}")
        sys.exit(1)

    index_to_path = list_items(COLL)
    if not index_to_path:
        print("[info] No indexed items found to process. Nothing to do.")
        return

    # Compute new indices without gaps starting at 1
    mapping = compute_new_indices(index_to_path)

    # Fast path: already contiguous 1..N in ascending order?
    old_sorted = sorted(index_to_path.keys())
    contiguous = all(old == new for new, old in enumerate(old_sorted, start=1))
    renamed_items = []
    if contiguous:
        print("[info] Indices already contiguous. Checking CSV only...")
    else:
        print("[info] Renaming items in two phases to pack indices...")
        renamed_items = two_phase_renames(mapping, index_to_path)
        print(f"[ok] Renames complete. {len(renamed_items)} items renamed.")


    # CSV sync
    csv_rows = load_csv(CSV_PATH)
    if csv_rows:
        # Backup
        try:
            shutil.copy2(CSV_PATH, CSV_BACKUP)
            print(f"[ok] Backed up CSV to {CSV_BACKUP.name}")
        except Exception as e:
            print(f"[warn] Could not back up CSV: {e}")

        kept, row_changes, removed_rows = sync_csv_to_mapping(csv_rows, mapping, set(index_to_path.keys()))
        write_csv(CSV_PATH, kept)

        print(f"[ok] CSV updated. Rows kept: {len(kept)}")
        if removed_rows:
            print("\n[removed rows]")
            for row in removed_rows:
                print(f"  Removed index {row[0]} → '{row[1]}' (no matching file)")
        if row_changes:
            print("\n[reindexed rows]")
            for old, new, title in row_changes:
                print(f"  {old} → {new} : {title}")
    else:
        row_changes, removed_rows = [], []

    print("\n=== SUMMARY ===")
    if renamed_items:
        print("Renamed files/folders:")
        for old, new in renamed_items:
            print(f"  {old} → {new}")
    else:
        print("No file renames needed.")
    if csv_rows:
        print(f"CSV rows total after sync: {len(kept)}")

if __name__ == "__main__":
    main()
