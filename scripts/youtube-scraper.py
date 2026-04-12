#!/usr/bin/env python3
"""
YouTube Channel Transcript Scraper
Extracts English captions from all videos on a YouTube channel or playlist.
Outputs transcripts as both individual .txt files and a combined .json file.

Usage:
    source .venv/bin/activate
    python scripts/youtube-scraper.py CHANNEL_URL_OR_HANDLE [--output-dir OUTPUT_DIR]

Examples:
    python scripts/youtube-scraper.py https://www.youtube.com/@YourChannel
    python scripts/youtube-scraper.py https://www.youtube.com/playlist?list=PLxxxxx
    python scripts/youtube-scraper.py @YourChannel --output-dir ./my-transcripts
"""

import argparse
import json
import os
import re
import sys
import time

try:
    from youtube_transcript_api import YouTubeTranscriptApi
except ImportError:
    print("Missing dependency. Run: pip install youtube-transcript-api")
    sys.exit(1)

try:
    import yt_dlp
except ImportError:
    print("Missing dependency. Run: pip install yt-dlp")
    sys.exit(1)


def get_video_ids(channel_or_playlist_url: str) -> list[dict]:
    """Extract all video IDs and titles from a channel or playlist URL."""
    if channel_or_playlist_url.startswith("@"):
        channel_or_playlist_url = f"https://www.youtube.com/{channel_or_playlist_url}"

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "skip_download": True,
    }

    if "playlist" not in channel_or_playlist_url.lower():
        url = channel_or_playlist_url.rstrip("/")
        if not url.endswith("/videos"):
            url += "/videos"
    else:
        url = channel_or_playlist_url

    print(f"Fetching video list from: {url}")

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        result = ydl.extract_info(url, download=False)

    videos = []
    if result and "entries" in result:
        for entry in result["entries"]:
            if entry and entry.get("id"):
                videos.append({
                    "id": entry["id"],
                    "title": entry.get("title", "Untitled"),
                })

    print(f"Found {len(videos)} videos")
    return videos


def fetch_transcript(video_id: str) -> str | None:
    """Fetch English transcript for a single video. Returns plain text or None."""
    api = YouTubeTranscriptApi()
    try:
        # First try: direct English fetch (manual or auto-generated)
        transcript = api.fetch(video_id, languages=["en"])
        lines = [snippet.text for snippet in transcript]
        return " ".join(lines)
    except Exception:
        pass

    # Second try: list all transcripts and find any we can use
    try:
        transcript_list = api.list(video_id)
        for t in transcript_list:
            # Grab any English variant (en, en-US, en-GB, etc.)
            if t.language_code.startswith("en"):
                fetched = t.fetch()
                lines = [snippet.text for snippet in fetched]
                return " ".join(lines)
        # Third try: translate any available transcript to English
        for t in transcript_list:
            if t.is_translatable and "en" in [lang.language_code for lang in t.translation_languages]:
                fetched = t.translate("en").fetch()
                lines = [snippet.text for snippet in fetched]
                return " ".join(lines)
    except Exception as e:
        print(f"  Could not fetch transcript: {e}")

    return None


def sanitize_filename(title: str) -> str:
    """Make a title safe for use as a filename."""
    clean = re.sub(r'[^\w\s-]', '', title)
    clean = re.sub(r'\s+', '_', clean.strip())
    return clean[:100]  # cap length


def main():
    parser = argparse.ArgumentParser(description="Scrape YouTube channel transcripts")
    parser.add_argument("url", help="YouTube channel URL, handle (@name), or playlist URL")
    parser.add_argument("--output-dir", default="./data/transcripts", help="Output directory (default: ./data/transcripts)")
    args = parser.parse_args()

    output_dir = args.output_dir
    os.makedirs(output_dir, exist_ok=True)
    txt_dir = os.path.join(output_dir, "individual")
    os.makedirs(txt_dir, exist_ok=True)

    # Step 1: Get all video IDs
    videos = get_video_ids(args.url)
    if not videos:
        print("No videos found. Check the URL and try again.")
        sys.exit(1)

    # Step 2: Fetch transcripts
    all_transcripts = []
    success = 0
    failed = 0

    for i, video in enumerate(videos, 1):
        vid = video["id"]
        title = video["title"]
        print(f"[{i}/{len(videos)}] {title} ({vid})...", end=" ")

        transcript_text = fetch_transcript(vid)

        if transcript_text:
            print("OK")
            success += 1

            # Save individual .txt
            safe_name = sanitize_filename(title)
            txt_path = os.path.join(txt_dir, f"{safe_name}.txt")
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(f"Title: {title}\n")
                f.write(f"Video ID: {vid}\n")
                f.write(f"URL: https://www.youtube.com/watch?v={vid}\n")
                f.write("---\n\n")
                f.write(transcript_text)

            all_transcripts.append({
                "video_id": vid,
                "title": title,
                "url": f"https://www.youtube.com/watch?v={vid}",
                "transcript": transcript_text,
            })
        else:
            print("SKIPPED (no English captions)")
            failed += 1

        # Be polite to YouTube's servers
        time.sleep(0.5)

    # Step 3: Save combined JSON
    json_path = os.path.join(output_dir, "all_transcripts.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(all_transcripts, f, indent=2, ensure_ascii=False)

    # Summary
    print("\n--- Done ---")
    print(f"Transcripts fetched: {success}")
    print(f"Skipped (no captions): {failed}")
    print(f"Individual files:     {txt_dir}/")
    print(f"Combined JSON:        {json_path}")


if __name__ == "__main__":
    main()
