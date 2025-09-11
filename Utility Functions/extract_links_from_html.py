#!/usr/bin/env python3

# Use if downloaded the full HTMl of a page including TikTok links
# Returns a file only containing tiktok posts (videos or slideshows)

import re
from bs4 import BeautifulSoup

def extract_tiktok_links(file_path, output_file="links.txt"):
    with open(file_path, 'r', encoding='utf-8') as file:
        content = file.read()
        soup = BeautifulSoup(content, 'html.parser')

        # Match TikTok video or photo URLs
        video_or_photo_pattern = re.compile(
            r"https://www\.tiktok\.com/@[\w\.\-]+/(video|photo)/\d+"
        )
        links = soup.find_all("a", href=video_or_photo_pattern)

        # Deduplicate while keeping order
        seen = set()
        urls = []
        for link in links[::-1]:  # reverse so oldest first
            url = link['href']
            if url not in seen:
                urls.append(url)
                seen.add(url)

    # Save to text file
    with open(output_file, "w", encoding="utf-8") as f:
        for url in urls:
            f.write(url + "\n")

    print(f"Saved {len(urls)} links to {output_file}")


if __name__ == "__main__":
    html_file = "example.htm"  # <-- replace with your .htm file
    extract_tiktok_links(html_file, "links.txt")
