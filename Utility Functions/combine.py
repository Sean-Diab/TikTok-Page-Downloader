import pandas as pd
import os
import shutil

# Combines two different downloads done in separate times using my program together.
# Name one folder 1 and the other one 2 (doesn't matter which)
# Extra videos from folder 2 get copied into folder 1, folder 1 will be the final product
# Make sure each folder has a collection folder and a downloads.csv created using my program (must follow my format)

# Video extensions to recognize
VIDEO_EXTS = {".mp4", ".webm", ".mkv", ".mov"}

def _starts_with_index(name: str, index_str: str) -> bool:
    """
    True if 'name' begins with the exact index followed by either a space ' ' or a dot '.'.
    Examples (index=10): '10.mp4' -> True, '10 something' -> True, '100.mp4' -> False
    """
    if not name.startswith(index_str):
        return False
    if len(name) == len(index_str):
        # Exact match (e.g., folder exactly named "10")
        return True
    nxt = name[len(index_str)]
    return nxt in (" ", ".")

def _find_video_path(downloads_path: str, original_index: int):
    """
    Look for a video file whose filename starts with the index and is followed by space or dot,
    and whose extension is in VIDEO_EXTS.
    Returns full path or None.
    """
    idx = str(original_index)
    candidates = []
    for entry in os.listdir(downloads_path):
        full = os.path.join(downloads_path, entry)
        if os.path.isfile(full):
            root, ext = os.path.splitext(entry)
            if ext.lower() in VIDEO_EXTS and _starts_with_index(entry, idx):
                candidates.append(full)
    if not candidates:
        return None
    # If multiple matches, pick lexicographically first for determinism
    candidates.sort()
    return candidates[0]

def _find_slideshow_folder(downloads_path: str, original_index: int):
    """
    Look for a folder whose name starts with the index and is followed by space or dot,
    OR exactly equals the index (to be extra tolerant).
    Returns full path or None.
    """
    idx = str(original_index)
    candidates = []
    for entry in os.listdir(downloads_path):
        full = os.path.join(downloads_path, entry)
        if os.path.isdir(full) and (_starts_with_index(entry, idx) or entry == idx):
            candidates.append(full)
    if not candidates:
        return None
    candidates.sort()
    return candidates[0]

def combine_collections():
    """
    Merges two TikTok download collections.

    This script identifies TikTok posts present in collection '2' but not in '1',
    appends their metadata to the CSV of collection '1' with a new index,
    and copies the corresponding video or image folder into the downloads
    directory of collection '1'.

    File/folder matching is relaxed:
      - Video files: name must start with the original index and the next character
        must be a space ' ' or a dot '.', and extension in VIDEO_EXTS.
      - Slideshow folders: name must start with the original index and the next
        character must be a space ' ' or a dot '.', or be exactly the index.
    """
    folder1_path = '1'
    folder2_path = '2'

    csv1_path = os.path.join(folder1_path, 'downloads.csv')
    csv2_path = os.path.join(folder2_path, 'downloads.csv')

    downloads1_path = os.path.join(folder1_path, 'collection')
    downloads2_path = os.path.join(folder2_path, 'collection')

    if not all([
        os.path.exists(csv1_path), os.path.exists(csv2_path),
        os.path.isdir(downloads1_path), os.path.isdir(downloads2_path)
    ]):
        print("Error: Make sure folders '1' and '2' exist and contain 'downloads.csv' and a 'collection' directory.")
        return

    try:
        df1 = pd.read_csv(csv1_path)
        df2 = pd.read_csv(csv2_path)

        urls1 = set(df1['URL']) if not df1.empty else set()
        urls2 = set(df2['URL']) if not df2.empty else set()

        new_urls = urls2 - urls1
        if not new_urls:
            print("No new TikToks found in collection '2'. Collection '1' is already up to date.")
            return

        print(f"Found {len(new_urls)} new TikToks to combine.")

        # Next index in collection 1
        next_index = 0 if df1.empty else int(df1['Index'].max()) + 1

        new_rows = []

        # Iterate in df2's original order to keep stable sequencing
        for _, row in df2.iterrows():
            url = row['URL']
            if url not in new_urls:
                continue

            original_index = int(row['Index'])
            title = row['Title'] if 'Title' in row and not pd.isna(row['Title']) else ''

            print(f"\nProcessing new item: Index {original_index} from collection 2 -> New Index {next_index}")

            # Append new row for CSV
            new_rows.append({'Index': next_index, 'Title': title, 'URL': url})

            # Locate source (video or slideshow folder) using relaxed matching
            video_src = _find_video_path(downloads2_path, original_index)
            folder_src = None if video_src else _find_slideshow_folder(downloads2_path, original_index)

            if video_src:
                # Keep destination strictly {index}.mp4 (normalize extension to the found one)
                _, ext = os.path.splitext(video_src)
                dest_video_path = os.path.join(downloads1_path, f"{next_index}{ext.lower()}")
                print(f"  Copying video file: {video_src} -> {dest_video_path}")
                shutil.copy2(video_src, dest_video_path)
            elif folder_src:
                dest_folder_path = os.path.join(downloads1_path, str(next_index))
                print(f"  Copying slideshow folder: {folder_src} -> {dest_folder_path}")
                shutil.copytree(folder_src, dest_folder_path, dirs_exist_ok=False)
            else:
                print(f"  Warning: Could not find a matching download for Index {original_index} in collection 2.")
                # Still increment index to keep CSV in sync with attempted copy
                next_index += 1
                continue

            next_index += 1

        # Append and save CSV
        if new_rows:
            new_rows_df = pd.DataFrame(new_rows)
            df1 = pd.concat([df1, new_rows_df], ignore_index=True)
            df1.to_csv(csv1_path, index=False)

        print(f"\nSuccessfully combined {len(new_rows)} new items into collection '1'.")
        print(f"Updated CSV saved to: {csv1_path}")

    except FileNotFoundError:
        print("Error: One of the CSV files was not found.")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

if __name__ == "__main__":
    combine_collections()
