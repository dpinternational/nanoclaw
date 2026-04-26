#!/usr/bin/env python3
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / "state"
STATE_DIR.mkdir(parents=True, exist_ok=True)
EVENTS_PATH = STATE_DIR / "glockapps_sync_events.jsonl"
SNAPSHOT_PATH = STATE_DIR / "glockapps_sync_snapshot.json"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def log_event(rec: dict) -> None:
    rec = {"ts": now_iso(), **rec}
    with EVENTS_PATH.open("a") as f:
        f.write(json.dumps(rec) + "\n")
    print(json.dumps(rec))


def load_cfg() -> dict:
    load_dotenv()
    return {
        "api_key": os.getenv("GLOCKAPPS_API_KEY", ""),
        "base": os.getenv(
            "GLOCKAPPS_API_BASE", "https://api.glockapps.com/gateway/spamtest-v2/api"
        ),
        "endpoint": os.getenv("GLOCKAPPS_API_ENDPOINT", ""),
        "project_id": os.getenv("GLOCKAPPS_PROJECT_ID", ""),
    }


def try_request(url: str, key: str) -> tuple[int, str, dict]:
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    # GlockApps v2 swagger documents apiKey as a required request parameter.
    r = requests.get(url, headers=headers, params={"apiKey": key}, timeout=30)
    return r.status_code, r.text[:500], dict(r.headers)


def main() -> int:
    cfg = load_cfg()
    if not cfg["api_key"]:
        log_event({"type": "config_error", "error": "missing_GLOCKAPPS_API_KEY"})
        return 1

    targets = []
    base = cfg["base"].rstrip("/")
    if cfg["endpoint"]:
        targets.append(base + "/" + cfg["endpoint"].lstrip("/"))
    elif cfg["project_id"]:
        # default operational mode: pull short test results for the selected project
        pid = cfg["project_id"]
        targets.extend(
            [
                base + f"/projects/{pid}/shortTestResults",
                base + f"/projects/{pid}/tests/list",
            ]
        )
    else:
        # probe mode when endpoint/project isn't configured yet
        targets.extend(
            [
                base + "/projects",
                base + "/providers",
                base + "/blocklistServers",
            ]
        )

    results = []
    for url in targets:
        try:
            status, body, headers = try_request(url, cfg["api_key"])
            results.append(
                {
                    "url": url,
                    "status": status,
                    "content_type": headers.get("Content-Type", ""),
                    "body_preview": body,
                }
            )
        except Exception as e:
            results.append({"url": url, "error": str(e)})

    SNAPSHOT_PATH.write_text(json.dumps({"captured_at": now_iso(), "results": results}, indent=2))

    ok = any(r.get("status") == 200 and "error" not in r for r in results)
    log_event(
        {
            "type": "glockapps_sync_probe",
            "ok": ok,
            "endpoint_configured": bool(cfg["endpoint"]),
            "project_configured": bool(cfg["project_id"]),
            "project_id": cfg["project_id"] or None,
            "results": results,
            "next_step": (
                "Set GLOCKAPPS_PROJECT_ID (recommended) or GLOCKAPPS_API_ENDPOINT"
                if not cfg["endpoint"] and not cfg["project_id"]
                else None
            ),
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
