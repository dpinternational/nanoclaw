#!/usr/bin/env python3
import hashlib
import hmac
import json
import os
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / "state"
LOG_DIR = ROOT / "logs"
STATE_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

RAW_EVENTS_PATH = STATE_DIR / "smartlead_webhook_events.jsonl"
RECEIVER_LOG_PATH = LOG_DIR / "smartlead_webhook_receiver.log"

RATE_LOCK = threading.Lock()
RATE_BUCKETS: dict[str, deque[float]] = defaultdict(deque)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8", errors="ignore")).hexdigest()


def load_cfg() -> dict:
    load_dotenv(ROOT / ".env")
    return {
        "SUPABASE_URL": os.getenv("SUPABASE_URL", "").strip(),
        "SUPABASE_KEY": os.getenv("SUPABASE_KEY", "").strip(),
        "HOST": os.getenv("SMARTLEAD_WEBHOOK_HOST", "0.0.0.0"),
        "PORT": int(os.getenv("SMARTLEAD_WEBHOOK_PORT", "3002")),
        "PATH": os.getenv("SMARTLEAD_WEBHOOK_PATH", "/smartlead/webhook"),
        "WEBHOOK_TOKEN": os.getenv("SMARTLEAD_WEBHOOK_TOKEN", "").strip(),
        "MAX_BODY_BYTES": int(os.getenv("SMARTLEAD_WEBHOOK_MAX_BODY_BYTES", "262144")),
        "RATE_LIMIT_PER_MIN": int(os.getenv("SMARTLEAD_WEBHOOK_RATE_LIMIT_PER_MIN", "120")),
    }


CFG = load_cfg()


def log_line(msg: str) -> None:
    line = f"{now_iso()} {msg}"
    with RECEIVER_LOG_PATH.open("a") as f:
        f.write(line + "\n")
    print(line, flush=True)


def supabase_headers() -> dict:
    return {
        "apikey": CFG["SUPABASE_KEY"],
        "Authorization": f"Bearer {CFG['SUPABASE_KEY']}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def upsert_supabase_event(row: dict) -> tuple[bool, str]:
    if not CFG["SUPABASE_URL"] or not CFG["SUPABASE_KEY"]:
        return False, "supabase_missing_env"
    url = f"{CFG['SUPABASE_URL']}/rest/v1/smartlead_webhook_events"
    headers = {**supabase_headers(), "Prefer": "resolution=merge-duplicates,return=minimal"}
    params = {"on_conflict": "event_hash"}
    r = requests.post(url, headers=headers, params=params, json=[row], timeout=20)
    if r.status_code in (200, 201, 204):
        return True, "ok"
    return False, f"http_{r.status_code}:{r.text[:300]}"


def is_rate_limited(client_ip: str) -> bool:
    limit = CFG["RATE_LIMIT_PER_MIN"]
    if limit <= 0:
        return False
    now = time.time()
    cutoff = now - 60
    with RATE_LOCK:
        bucket = RATE_BUCKETS[client_ip]
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= limit:
            return True
        bucket.append(now)
    return False


def safe_header_subset(headers) -> dict:
    keep = {
        "user-agent",
        "content-type",
        "content-length",
        "x-forwarded-for",
        "x-real-ip",
        "cf-connecting-ip",
    }
    return {k.lower(): v for k, v in headers.items() if k.lower() in keep}


def extract_client_ip(headers, fallback_ip: str) -> str:
    for h in ("x-forwarded-for", "x-real-ip", "cf-connecting-ip"):
        v = headers.get(h)
        if v:
            return v.split(",")[0].strip()
    return fallback_ip


class Handler(BaseHTTPRequestHandler):
    server_version = "SmartleadWebhookReceiver/1.1"

    def _send_json(self, code: int, payload: dict):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/health", "/healthz"):
            self._send_json(200, {"ok": True, "service": "smartlead-webhook-receiver", "ts": now_iso()})
            return
        self._send_json(404, {"ok": False, "error": "not_found"})

    def do_POST(self):
        parsed = urlsplit(self.path)
        request_path = parsed.path
        query = parse_qs(parsed.query)

        if request_path != CFG["PATH"]:
            self._send_json(404, {"ok": False, "error": "not_found"})
            return

        client_ip = extract_client_ip({k.lower(): v for k, v in self.headers.items()}, self.client_address[0])
        if is_rate_limited(client_ip):
            log_line(f"rate_limited client_ip={client_ip}")
            self._send_json(429, {"ok": False, "error": "rate_limited"})
            return

        expected_token = CFG["WEBHOOK_TOKEN"]
        if expected_token:
            header_token = self.headers.get("X-Webhook-Token", "").strip()
            query_token = (query.get("token") or [""])[0].strip()
            provided = header_token or query_token
            if not provided or not hmac.compare_digest(provided, expected_token):
                log_line(f"auth_failed client_ip={client_ip}")
                self._send_json(401, {"ok": False, "error": "unauthorized"})
                return

        try:
            content_len = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_json(400, {"ok": False, "error": "invalid_content_length"})
            return

        if content_len < 0:
            self._send_json(400, {"ok": False, "error": "invalid_content_length"})
            return

        if content_len > CFG["MAX_BODY_BYTES"]:
            self._send_json(413, {"ok": False, "error": "payload_too_large"})
            return

        raw_bytes = self.rfile.read(content_len) if content_len > 0 else b""
        if len(raw_bytes) > CFG["MAX_BODY_BYTES"]:
            self._send_json(413, {"ok": False, "error": "payload_too_large"})
            return

        raw_text = raw_bytes.decode("utf-8", errors="replace")

        try:
            payload = json.loads(raw_text) if raw_text.strip() else {}
        except Exception:
            payload = {"_raw_unparsed": raw_text}

        event_hash = sha256_text(raw_text if raw_text else json.dumps(payload, sort_keys=True))
        event_type = payload.get("event") or payload.get("event_type") or payload.get("type")

        lead_email = None
        if isinstance(payload.get("lead"), dict):
            lead_email = payload["lead"].get("email")
        if not lead_email:
            lead_email = payload.get("lead_email")
        if not lead_email:
            lead_email = payload.get("to_email")
        if not lead_email:
            lead_email = payload.get("email")

        row = {
            "received_at": now_iso(),
            "event_hash": event_hash,
            "event_type": event_type,
            "campaign_id": payload.get("campaign_id"),
            "lead_id": payload.get("lead_id"),
            "lead_email": lead_email,
            "webhook_url_path": CFG["PATH"],
            "request_headers": safe_header_subset(self.headers),
            "payload": payload,
            "raw_payload": raw_text,
        }

        with RAW_EVENTS_PATH.open("a") as f:
            f.write(json.dumps(row) + "\n")

        ok, msg = upsert_supabase_event(row)
        log_line(
            f"event_type={event_type} campaign_id={payload.get('campaign_id')} "
            f"lead_id={payload.get('lead_id')} client_ip={client_ip} supabase={msg}"
        )

        if not ok:
            self._send_json(503, {"ok": False, "stored": True, "supabase": False, "event_hash": event_hash})
            return

        self._send_json(200, {"ok": True, "stored": True, "supabase": True, "event_hash": event_hash})

    def log_message(self, fmt, *args):
        # keep default noisy logs out of stderr; we use structured log_line instead
        return


def main() -> int:
    host = CFG["HOST"]
    port = CFG["PORT"]
    path = CFG["PATH"]
    httpd = ThreadingHTTPServer((host, port), Handler)
    log_line(
        f"starting host={host} port={port} path={path} "
        f"max_body={CFG['MAX_BODY_BYTES']} rate_limit_per_min={CFG['RATE_LIMIT_PER_MIN']} "
        f"token_required={bool(CFG['WEBHOOK_TOKEN'])}"
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        log_line("shutdown_requested")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
