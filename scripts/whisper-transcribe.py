#!/usr/bin/env python3
"""Download audio from YouTube videos and transcribe with OpenAI Whisper API.
For videos that don't have YouTube captions available.
Has resume support — safe to re-run if interrupted."""

import json
import os
import re
import subprocess
import sys
import tempfile
import time

from openai import OpenAI

TXT_DIR = "./data/transcripts/individual"
JSON_PATH = "./data/transcripts/all_transcripts.json"
MISSING_PATH = "./data/transcripts/missing_ids.json"
WHISPER_PROGRESS = "./data/transcripts/whisper_progress.json"

client = OpenAI()


def sanitize_filename(title: str) -> str:
    clean = re.sub(r"[^\w\s-]", "", title)
    clean = re.sub(r"\s+", "_", clean.strip())
    return clean[:100]


def download_audio(video_id: str, output_path: str) -> bool:
    """Download audio as mp3 using yt-dlp + ffmpeg."""
    cmd = [
        "yt-dlp",
        "--extract-audio",
        "--audio-format", "mp3",
        "--audio-quality", "5",  # lower quality = smaller file = faster upload
        "--js-runtimes", "node:/usr/local/bin/node",
        "--no-warnings",
        "--quiet",
        "-o", output_path,
        f"https://www.youtube.com/watch?v={video_id}",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        # yt-dlp may append .mp3 to the output path
        possible_paths = [output_path, output_path + ".mp3", output_path.replace(".mp3", "") + ".mp3"]
        for p in possible_paths:
            if os.path.exists(p):
                return True
        return False
    except Exception as e:
        print(f"Download error: {e}")
        return False


def find_audio_file(base_path: str) -> str | None:
    """Find the actual audio file (yt-dlp may add extensions)."""
    possible = [base_path, base_path + ".mp3", base_path.replace(".mp3", "") + ".mp3"]
    for p in possible:
        if os.path.exists(p):
            return p
    return None


def split_audio(audio_path: str, tmpdir: str, chunk_minutes: int = 20) -> list[str]:
    """Split audio into chunks for Whisper API (25MB limit). Returns list of chunk paths."""
    # Check file size — if under 24MB, no need to split
    size_mb = os.path.getsize(audio_path) / (1024 * 1024)
    if size_mb < 24:
        return [audio_path]

    # Get duration
    probe = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "csv=p=0", audio_path],
        capture_output=True, text=True
    )
    duration = float(probe.stdout.strip())
    chunk_seconds = chunk_minutes * 60
    chunks = []

    for i, start in enumerate(range(0, int(duration) + 1, chunk_seconds)):
        chunk_path = os.path.join(tmpdir, f"chunk_{i:03d}.mp3")
        subprocess.run([
            "ffmpeg", "-y", "-i", audio_path,
            "-ss", str(start), "-t", str(chunk_seconds),
            "-acodec", "libmp3lame", "-q:a", "5",
            "-loglevel", "error",
            chunk_path
        ], capture_output=True)
        if os.path.exists(chunk_path) and os.path.getsize(chunk_path) > 1000:
            chunks.append(chunk_path)

    return chunks if chunks else [audio_path]


def transcribe_audio(audio_path: str) -> str | None:
    """Transcribe audio file using OpenAI Whisper API. Handles large files by splitting."""
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            chunks = split_audio(audio_path, tmpdir)
            all_text = []

            for chunk in chunks:
                with open(chunk, "rb") as f:
                    transcript = client.audio.transcriptions.create(
                        model="whisper-1",
                        file=f,
                        language="en",
                    )
                all_text.append(transcript.text)

            return " ".join(all_text)
    except Exception as e:
        print(f"Transcription error: {e}")
        return None


def main():
    with open(MISSING_PATH) as f:
        missing = json.load(f)

    # Load progress
    done_ids = set()
    if os.path.exists(WHISPER_PROGRESS):
        with open(WHISPER_PROGRESS) as f:
            done_ids = set(json.load(f))

    remaining = [v for v in missing if v["id"] not in done_ids]
    print(f"Total missing: {len(missing)}, already done: {len(done_ids)}, remaining: {len(remaining)}")
    print(f"Using OpenAI Whisper API for transcription\n", flush=True)

    new_transcripts = []
    success = 0
    failed = 0

    for i, v in enumerate(remaining, 1):
        vid, title = v["id"], v["title"]
        print(f"[{i}/{len(remaining)}] {title} ({vid})", flush=True)

        with tempfile.TemporaryDirectory() as tmpdir:
            audio_base = os.path.join(tmpdir, f"{vid}.mp3")

            # Step 1: Download audio
            print(f"  Downloading...", end=" ", flush=True)
            if not download_audio(vid, audio_base):
                print("FAILED (download)")
                failed += 1
                done_ids.add(vid)
                with open(WHISPER_PROGRESS, "w") as f:
                    json.dump(list(done_ids), f)
                continue

            audio_file = find_audio_file(audio_base)
            if not audio_file:
                print("FAILED (no audio file)")
                failed += 1
                done_ids.add(vid)
                with open(WHISPER_PROGRESS, "w") as f:
                    json.dump(list(done_ids), f)
                continue

            size_mb = os.path.getsize(audio_file) / (1024 * 1024)
            print(f"OK ({size_mb:.1f}MB)", flush=True)

            # Step 2: Transcribe
            print(f"  Transcribing...", end=" ", flush=True)
            text = transcribe_audio(audio_file)

            if text and len(text) > 50:
                print(f"OK ({len(text.split())} words)")
                success += 1

                # Save individual txt
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
                print("FAILED (no text)")
                failed += 1

        # Save progress after each video
        done_ids.add(vid)
        with open(WHISPER_PROGRESS, "w") as f:
            json.dump(list(done_ids), f)

        # Small delay between videos
        time.sleep(1)

    # Merge with existing JSON
    with open(JSON_PATH) as f:
        existing = json.load(f)
    all_data = existing + new_transcripts
    with open(JSON_PATH, "w") as f:
        json.dump(all_data, f, indent=2, ensure_ascii=False)

    print(f"\n--- Done ---")
    print(f"New transcripts: {success}")
    print(f"Failed: {failed}")
    print(f"Total transcripts: {len(all_data)}")
    print(f"Total words: {sum(len(t['transcript'].split()) for t in all_data):,}")


if __name__ == "__main__":
    main()
