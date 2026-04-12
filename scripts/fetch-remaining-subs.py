#!/usr/bin/env python3
"""Fetch auto-generated English subtitles for videos that were skipped.
Uses yt-dlp with delays to avoid rate limiting."""

import json
import os
import re
import subprocess
import sys
import tempfile
import time

TXT_DIR = "./data/transcripts/individual"
JSON_PATH = "./data/transcripts/all_transcripts.json"
MISSING_PATH = "./data/transcripts/missing_ids.json"
PROGRESS_PATH = "./data/transcripts/fetch_progress.json"
DELAY_BETWEEN = 8  # seconds between requests


def parse_vtt(vtt_content: str) -> str:
    lines = []
    seen = set()
    for line in vtt_content.split("\n"):
        line = line.strip()
        if (not line or line.startswith("WEBVTT") or line.startswith("Kind:")
                or line.startswith("Language:") or "-->" in line
                or re.match(r"^\d+$", line) or line.startswith("NOTE")):
            continue
        clean = re.sub(r"<[^>]+>", "", line).strip()
        if clean and clean not in seen:
            seen.add(clean)
            lines.append(clean)
    return " ".join(lines)


def sanitize_filename(title: str) -> str:
    clean = re.sub(r"[^\w\s-]", "", title)
    clean = re.sub(r"\s+", "_", clean.strip())
    return clean[:100]


def fetch_one(vid: str, title: str) -> str | None:
    with tempfile.TemporaryDirectory() as tmpdir:
        cmd = [
            "yt-dlp",
            "--write-auto-sub",
            "--write-sub",
            "--sub-lang", "en",
            "--sub-format", "vtt",
            "--skip-download",
            "--js-runtimes", f"node:/usr/local/bin/node",
            "--no-warnings",
            "-o", os.path.join(tmpdir, "%(id)s.%(ext)s"),
            f"https://www.youtube.com/watch?v={vid}",
        ]
        subprocess.run(cmd, capture_output=True, text=True, timeout=45)

        vtt_files = [f for f in os.listdir(tmpdir) if f.endswith(".vtt")]
        if not vtt_files:
            return None

        with open(os.path.join(tmpdir, vtt_files[0]), "r", encoding="utf-8") as fh:
            text = parse_vtt(fh.read())

        return text if len(text) >= 50 else None


def main():
    with open(MISSING_PATH) as f:
        missing = json.load(f)

    # Load progress (resume support)
    done_ids = set()
    if os.path.exists(PROGRESS_PATH):
        with open(PROGRESS_PATH) as f:
            done_ids = set(json.load(f))

    remaining = [v for v in missing if v["id"] not in done_ids]
    print(f"Total missing: {len(missing)}, already done: {len(done_ids)}, remaining: {len(remaining)}")
    print(f"Delay between requests: {DELAY_BETWEEN}s")
    print(f"Estimated time: ~{len(remaining) * DELAY_BETWEEN // 60} minutes\n", flush=True)

    new_transcripts = []
    success = 0
    failed = 0
    rate_limited = 0

    for i, v in enumerate(remaining, 1):
        vid, title = v["id"], v["title"]
        print(f"[{i}/{len(remaining)}] {title} ({vid})...", end=" ", flush=True)

        text = fetch_one(vid, title)

        if text:
            print("OK")
            success += 1

            safe_name = sanitize_filename(title)
            with open(os.path.join(TXT_DIR, f"{safe_name}.txt"), "w", encoding="utf-8") as fh:
                fh.write(f"Title: {title}\n")
                fh.write(f"Video ID: {vid}\n")
                fh.write(f"URL: https://www.youtube.com/watch?v={vid}\n")
                fh.write("---\n\n")
                fh.write(text)

            new_transcripts.append({
                "video_id": vid,
                "title": title,
                "url": f"https://www.youtube.com/watch?v={vid}",
                "transcript": text,
            })
        else:
            print("SKIPPED")
            failed += 1

        # Save progress
        done_ids.add(vid)
        with open(PROGRESS_PATH, "w") as f:
            json.dump(list(done_ids), f)

        # Delay to avoid rate limiting
        if i < len(remaining):
            time.sleep(DELAY_BETWEEN)

    # Merge with existing JSON
    with open(JSON_PATH) as f:
        existing = json.load(f)
    all_data = existing + new_transcripts
    with open(JSON_PATH, "w") as f:
        json.dump(all_data, f, indent=2, ensure_ascii=False)

    print(f"\n--- Done ---")
    print(f"New transcripts: {success}")
    print(f"Skipped: {failed}")
    print(f"Total transcripts: {len(all_data)}")
    print(f"Total words: {sum(len(t['transcript'].split()) for t in all_data):,}")


if __name__ == "__main__":
    main()
