Downloads all posts on a TikTok page and stream videos locally on a neat HTML file! (Comes with a lot of extra utility functions)

Important information gets deleted and censored online. Do not trust that your videos will be safe.

How to run:

1. Go to the TikTok page where you want to download all the posts (could be a collection, all saved posts, another person's profile, etc.)

2. Press f12 to go into the console and run this command that scrolls all the way down on a page and gets all links:

(async () => {
  // Collect as we go (handles virtualization)
  const seen = new Set();
  const out = [];

  const collect = () => {
    // Grab both video and photo post URLs
    const anchors = document.querySelectorAll('a[href*="/video/"], a[href*="/photo/"]');
    for (const a of anchors) {
      try {
        let u = new URL(a.href, location.href);
        // Normalize: strip tracking params/fragments
        u.search = "";
        u.hash = "";
        const url = u.toString();
        if (!seen.has(url)) {
          seen.add(url);
          out.push(url);
        }
      } catch {}
    }
  };

  // Smooth auto-scroll until no new items appear for a few cycles
  let lastCount = 0;
  let idle = 0;
  const idleThreshold = 6;        // ~6 cycles of no growth
  const pauseMs = 1200;           // wait per cycle to let items render/fetch
  const maxCycles = 20000;        // hard safety cap

  for (let cycle = 0; cycle < maxCycles; cycle++) {
    collect();
    window.scrollBy(0, document.documentElement.scrollHeight);
    await new Promise(r => setTimeout(r, pauseMs));
    collect();

    if (seen.size > lastCount) {
      lastCount = seen.size;
      idle = 0;
    } else {
      idle++;
    }
    if (idle >= idleThreshold) break;
  }

  // Reverse the collected list (oldest first)
  const reversed = out.slice().reverse();

  // Create and download links.txt
  const blob = new Blob([reversed.join("\n") + "\n"], { type: "text/plain" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "links.txt";
  a.click();
  URL.revokeObjectURL(a.href);
  console.log(`Saved ${reversed.length} unique links (oldest first) to links.txt`);
})();

3. Put that links.txt in the same directory as the python scripts

4. Run 1.py

5. Run build_archive.py

You can also put a new links.txt (can even include old links) in the same directory and run as well, will append extra files on top and update the HTML file!


Now you can use the HTML file to look at the posts that are saved locally on your computer! Enjoy!
