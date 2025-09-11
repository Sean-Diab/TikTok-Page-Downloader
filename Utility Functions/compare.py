#!/usr/bin/env python3
# compare_links.py
#
# Compare two text files of TikTok links and show which links
# are missing in each file.

def read_links(file_path):
    """Read lines from file, strip whitespace, ignore blanks."""
    with open(file_path, "r", encoding="utf-8") as f:
        return {line.strip() for line in f if line.strip()}

def compare_files(file1, file2):
    links1 = read_links(file1)
    links2 = read_links(file2)

    only_in_file1 = sorted(links1 - links2)
    only_in_file2 = sorted(links2 - links1)

    print(f"Links in {file1} but not in {file2}:")
    for link in only_in_file1:
        print(link)
    if not only_in_file1:
        print("  None")

    print("\nLinks in {file2} but not in {file1}:")
    for link in only_in_file2:
        print(link)
    if not only_in_file2:
        print("  None")

if __name__ == "__main__":
    # Example usage: python compare_links.py links1.txt links2.txt
    import sys
    if len(sys.argv) != 3:
        print("Usage: python compare_links.py file1.txt file2.txt")
        sys.exit(1)
    compare_files(sys.argv[1], sys.argv[2])
