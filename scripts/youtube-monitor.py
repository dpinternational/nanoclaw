#!/usr/bin/env python3
"""Monitor David's YouTube channel for new videos.
Downloads transcript and adds to story vault.
Outputs JSON with video info for NanoClaw to process."""

import json
import os
import re
import subprocess
import sys
import tempfile

# Config
CHANNEL_URL = "https://www.youtube.com/@DavidPriceOfficial/videos"
TRACKING_FILE = "./data/transcripts/known_video_ids.json"
TRANSCRIPT_JSON = "./data/transcripts/all_transcripts.json"
STORY_VAULT = "./groups/telegram_braindump/story-vault.md"
TXT_DIR = "./data/transcripts/individual"


def get_latest_videos(count=5):
    """Fetch the most recent videos from the channel."""
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "skip_download": True,
        "playlistend": count,
    }
    try:
        import yt_dlp
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            result = ydl.extract_info(CHANNEL_URL, download=False)
        if result and "entries" in result:
            return [{"id": e["id"], "title": e.get("title", "Untitled")} for e in result["entries"] if e and e.get("id")]
    except Exception as e:
        print(f"Error fetching videos: {e}", file=sys.stderr)
    return []


def load_known_ids():
    if os.path.exists(TRACKING_FILE):
        with open(TRACKING_FILE) as f:
            return set(json.load(f))
    # First run: load all existing transcript IDs
    if os.path.exists(TRANSCRIPT_JSON):
        with open(TRANSCRIPT_JSON) as f:
            data = json.load(f)
        ids = {t["video_id"] for t in data}
        save_known_ids(ids)
        return ids
    return set()


def save_known_ids(ids):
    with open(TRACKING_FILE, "w") as f:
        json.dump(list(ids), f)


def transcribe_video(video_id, title):
    """Download audio and transcribe via Whisper API."""
    openai_key = None
    try:
        with open(".env") as f:
            for line in f:
                if line.startswith("OPENAI_API_KEY="):
                    openai_key = line.strip().split("=", 1)[1]
    except FileNotFoundError:
        pass

    if not openai_key:
        print("No OPENAI_API_KEY in .env", file=sys.stderr)
        return None

    with tempfile.TemporaryDirectory() as tmpdir:
        audio_base = os.path.join(tmpdir, f"{video_id}.mp3")
        cmd = [
            "yt-dlp", "--extract-audio", "--audio-format", "mp3",
            "--audio-quality", "5", "--no-warnings", "--quiet",
            "-o", audio_base,
            f"https://www.youtube.com/watch?v={video_id}",
        ]
        subprocess.run(cmd, capture_output=True, text=True, timeout=120)

        # Find audio file
        audio_file = None
        for p in [audio_base, audio_base + ".mp3", audio_base.replace(".mp3", "") + ".mp3"]:
            if os.path.exists(p):
                audio_file = p
                break
        if not audio_file:
            return None

        # Transcribe via Whisper
        import http.client
        import mimetypes
        from email.mime.multipart import MIMEMultipart

        # Use curl for simplicity
        result = subprocess.run([
            "curl", "-s", "-X", "POST",
            "https://api.openai.com/v1/audio/transcriptions",
            "-H", f"Authorization: Bearer {openai_key}",
            "-F", f"file=@{audio_file}",
            "-F", "model=whisper-1",
            "-F", "language=en",
        ], capture_output=True, text=True, timeout=300)

        try:
            data = json.loads(result.stdout)
            return data.get("text")
        except (json.JSONDecodeError, KeyError):
            # File might be too large, try splitting
            return transcribe_large(audio_file, openai_key, tmpdir)


def transcribe_large(audio_file, api_key, tmpdir):
    """Split large audio and transcribe in chunks."""
    probe = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "csv=p=0", audio_file],
        capture_output=True, text=True
    )
    try:
        duration = float(probe.stdout.strip())
    except ValueError:
        return None

    chunk_seconds = 1200  # 20 min
    texts = []
    for i, start in enumerate(range(0, int(duration) + 1, chunk_seconds)):
        chunk_path = os.path.join(tmpdir, f"chunk_{i:03d}.mp3")
        subprocess.run([
            "ffmpeg", "-y", "-i", audio_file,
            "-ss", str(start), "-t", str(chunk_seconds),
            "-acodec", "libmp3lame", "-q:a", "5", "-loglevel", "error",
            chunk_path
        ], capture_output=True)
        if not os.path.exists(chunk_path):
            continue

        result = subprocess.run([
            "curl", "-s", "-X", "POST",
            "https://api.openai.com/v1/audio/transcriptions",
            "-H", f"Authorization: Bearer {api_key}",
            "-F", f"file=@{chunk_path}",
            "-F", "model=whisper-1",
            "-F", "language=en",
        ], capture_output=True, text=True, timeout=300)

        try:
            data = json.loads(result.stdout)
            if data.get("text"):
                texts.append(data["text"])
        except (json.JSONDecodeError, KeyError):
            pass

    return " ".join(texts) if texts else None


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
        print(f"New video detected: {title}", file=sys.stderr)

        text = transcribe_video(vid, title)
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
            print(f"  Transcribed: {word_count:,} words", file=sys.stderr)
        else:
            print(f"  Failed to transcribe", file=sys.stderr)

        known.add(vid)

    save_known_ids(known)
    print(json.dumps({"new_videos": results}))


if __name__ == "__main__":
    main()
