#!/usr/bin/env python3
"""Monitor David's YouTube channel for new videos.
Uses free YouTube captions instead of Whisper.
Saves transcripts and adds to content pipeline."""

import json
import os
import re
import sys

# Config — relative paths resolve from nanoclaw root
CHANNEL_URL = "https://www.youtube.com/@DavidPriceOfficial/videos"
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRACKING_FILE = os.path.join(BASE_DIR, "data/transcripts/known_video_ids.json")
TRANSCRIPT_JSON = os.path.join(BASE_DIR, "data/transcripts/all_transcripts.json")
STORY_VAULT = os.path.join(BASE_DIR, "groups/telegram_braindump/story-vault.md")
TXT_DIR = os.path.join(BASE_DIR, "data/transcripts/individual")


def get_latest_videos(count=5):
    """Fetch the most recent videos from the channel."""
    try:
        import yt_dlp
        ydl_opts = {
            "quiet": True, "no_warnings": True,
            "extract_flat": True, "skip_download": True,
            "playlistend": count,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            result = ydl.extract_info(CHANNEL_URL, download=False)
        if result and "entries" in result:
            return [{"id": e["id"], "title": e.get("title", "Untitled")}
                    for e in result["entries"] if e and e.get("id")]
    except Exception as e:
        print(f"Error fetching videos: {e}", file=sys.stderr)
    return []


def get_transcript(video_id):
    """Get transcript using free YouTube captions (no API key needed)."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        api = YouTubeTranscriptApi()
        segments = api.fetch(video_id)
        text = " ".join(seg.text for seg in segments)
        return text
    except Exception as e:
        print(f"  Captions error for {video_id}: {e}", file=sys.stderr)
        return None


def load_known_ids():
    if os.path.exists(TRACKING_FILE):
        with open(TRACKING_FILE) as f:
            return set(json.load(f))
    if os.path.exists(TRANSCRIPT_JSON):
        with open(TRANSCRIPT_JSON) as f:
            data = json.load(f)
        ids = {t.get("video_id", "") for t in data}
        save_known_ids(ids)
        return ids
    return set()


def save_known_ids(ids):
    os.makedirs(os.path.dirname(TRACKING_FILE), exist_ok=True)
    with open(TRACKING_FILE, "w") as f:
        json.dump(list(ids), f)


def sanitize_filename(title):
    clean = re.sub(r"[^\w\s-]", "", title)
    clean = re.sub(r"\s+", "_", clean.strip())
    return clean[:100]


def save_transcript(video_id, title, text):
    """Save to individual file and append to all_transcripts.json."""
    os.makedirs(TXT_DIR, exist_ok=True)

    # Individual file
    safe_name = sanitize_filename(title)
    with open(os.path.join(TXT_DIR, f"{safe_name}.txt"), "w", encoding="utf-8") as f:
        f.write(f"Title: {title}\n")
        f.write(f"Video ID: {video_id}\n")
        f.write(f"URL: https://www.youtube.com/watch?v={video_id}\n")
        f.write("---\n\n")
        f.write(text)

    # Append to JSON
    entry = {
        "video_id": video_id,
        "title": title,
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "transcript": text,
    }
    existing = []
    if os.path.exists(TRANSCRIPT_JSON):
        with open(TRANSCRIPT_JSON) as f:
            existing = json.load(f)
    existing.append(entry)
    with open(TRANSCRIPT_JSON, "w") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)

    return entry


def append_to_story_vault(title, text, word_count):
    """Add new video to the story vault."""
    excerpt = " ".join(text.split()[:2000])
    entry = f"\n### {title} ({word_count:,} words total) [NEW]\n\n{excerpt}\n\n"
    with open(STORY_VAULT, "a", encoding="utf-8") as f:
        f.write(entry)


def main():
    latest = get_latest_videos(5)
    if not latest:
        print(json.dumps({"new_videos": []}))
        return

    known = load_known_ids()
    new_videos = [v for v in latest if v["id"] not in known]

    if not new_videos:
        print(json.dumps({"new_videos": []}))
        return

    results = []
    for v in new_videos:
        vid, title = v["id"], v["title"]
        print(f"New video: {title}", file=sys.stderr)

        text = get_transcript(vid)
        if text and len(text) > 50:
            word_count = len(text.split())
            save_transcript(vid, title, text)
            append_to_story_vault(title, text, word_count)
            results.append({
                "video_id": vid,
                "title": title,
                "word_count": word_count,
                "url": f"https://www.youtube.com/watch?v={vid}",
            })
            print(f"  Saved: {word_count:,} words", file=sys.stderr)
        else:
            print(f"  No captions available", file=sys.stderr)

        known.add(vid)

    save_known_ids(known)
    print(json.dumps({"new_videos": results}))


if __name__ == "__main__":
    main()
