#!/usr/bin/env python3
import json
import os
import re
import subprocess
import sys
import time
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / "state"
LOG_DIR = ROOT / "logs"
STATE_FILE = STATE_DIR / "phase1_breaker_state.json"
EVENTS_FILE = STATE_DIR / "phase1_events.jsonl"

COMPOSE_FILE = os.getenv("SCRAPER_COMPOSE_FILE", str(ROOT / "docker-compose.multi.yml"))
W1 = os.getenv("SCRAPER_W1_SERVICE", "scraper_w1")
W2 = os.getenv("SCRAPER_W2_SERVICE", "scraper_w2")
WINDOW_MIN = int(os.getenv("PHASE1_WINDOW_MIN", "10"))
FAIL_THRESHOLD = int(os.getenv("PHASE1_FAIL_THRESHOLD", "3"))
RESTART_THRESHOLD = int(os.getenv("PHASE1_RESTART_THRESHOLD", "3"))
COOLDOWN_MIN = int(os.getenv("PHASE1_COOLDOWN_MIN", "60"))
GRACE_MIN = int(os.getenv("PHASE1_GRACE_MIN", "5"))
AUTO_START_W1 = os.getenv("PHASE1_AUTO_START_W1", "true").lower() == "true"
AUTO_RECOVER_W2 = os.getenv("PHASE1_AUTO_RECOVER_W2", "false").lower() == "true"

DOCKER_BIN = os.getenv("DOCKER_BIN")
if not DOCKER_BIN:
    _path = ":".join([
        os.environ.get("PATH", ""),
        "/opt/homebrew/bin",
        "/usr/local/bin",
        "/Applications/Docker.app/Contents/Resources/bin",
    ])
    DOCKER_BIN = shutil.which("docker", path=_path) or "docker"

RE_SEARCH_FAIL = re.compile(r"Search attempt\s+\d+/\d+ failed", re.IGNORECASE)
RE_RESTART = re.compile(r"Restarting Chrome driver", re.IGNORECASE)
RE_HARD = re.compile(r"\b(403|429)\b|captcha", re.IGNORECASE)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run(cmd: list[str]) -> tuple[int, str, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True)
        return p.returncode, p.stdout.strip(), p.stderr.strip()
    except FileNotFoundError as e:
        return 127, "", f"{e}. PATH={os.environ.get('PATH', '')}"


def dcmd(*args: str) -> list[str]:
    return [DOCKER_BIN, "compose", "-f", COMPOSE_FILE, *args]


def ensure_dirs() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {"breaker_open_until": 0, "last_reason": "", "last_action_at": ""}
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {"breaker_open_until": 0, "last_reason": "", "last_action_at": ""}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2))


def append_event(event_type: str, details: dict) -> None:
    rec = {"ts": now_iso(), "type": event_type, **details}
    with EVENTS_FILE.open("a") as f:
        f.write(json.dumps(rec) + "\n")
    print(json.dumps(rec))


def running_services() -> set[str]:
    code, out, err = run(dcmd("ps", "--status", "running", "--services"))
    if code != 0:
        append_event("compose_error", {"error": err or out})
        return set()
    return {line.strip() for line in out.splitlines() if line.strip()}


def service_logs(service: str, since_minutes: int) -> str:
    code, out, err = run(dcmd("logs", "--since", f"{since_minutes}m", "--no-color", service))
    if code != 0:
        append_event("logs_error", {"service": service, "error": err or out})
        return ""
    return out


def stop_service(service: str) -> bool:
    code, out, err = run(dcmd("stop", service))
    ok = code == 0
    append_event("service_stop", {"service": service, "ok": ok, "msg": out or err})
    return ok


def start_service(service: str) -> bool:
    code, out, err = run(dcmd("up", "-d", service))
    ok = code == 0
    append_event("service_start", {"service": service, "ok": ok, "msg": out or err})
    return ok


def parse_w2_health(log_text: str) -> dict:
    search_fail = len(RE_SEARCH_FAIL.findall(log_text))
    restarts = len(RE_RESTART.findall(log_text))
    hard_hits = len(RE_HARD.findall(log_text))
    return {
        "search_failures": search_fail,
        "restarts": restarts,
        "hard_hits": hard_hits,
    }


def service_uptime_seconds(service: str) -> Optional[int]:
    code, container_id, err = run(dcmd("ps", "-q", service))
    if code != 0 or not container_id:
        return None

    code, started_at_raw, err = run([DOCKER_BIN, "inspect", "-f", "{{.State.StartedAt}}", container_id])
    if code != 0 or not started_at_raw:
        return None

    try:
        started_at = datetime.fromisoformat(started_at_raw.replace("Z", "+00:00"))
        return int((datetime.now(timezone.utc) - started_at).total_seconds())
    except Exception:
        return None


def main() -> int:
    ensure_dirs()
    state = load_state()
    now_ts = time.time()

    running = running_services()

    # Keep worker1 up by default
    if W1 not in running and AUTO_START_W1:
        append_event("w1_not_running", {"action": "start"})
        start_service(W1)
        running = running_services()

    # If breaker open, keep W2 down until cooldown expires
    open_until = float(state.get("breaker_open_until", 0) or 0)
    breaker_open = now_ts < open_until

    if breaker_open and W2 in running:
        append_event("breaker_enforced", {"service": W2, "open_until": open_until})
        stop_service(W2)
        running = running_services()

    if breaker_open:
        append_event("breaker_open", {
            "service": W2,
            "seconds_remaining": int(open_until - now_ts),
            "last_reason": state.get("last_reason", "")
        })
        return 0

    # Optional auto-recover W2
    if W2 not in running and AUTO_RECOVER_W2:
        append_event("w2_recover_attempt", {"action": "start"})
        start_service(W2)
        running = running_services()

    # If W2 is running, evaluate error thresholds
    if W2 in running:
        uptime = service_uptime_seconds(W2)
        grace_seconds = GRACE_MIN * 60
        if uptime is not None and uptime < grace_seconds:
            append_event("w2_grace", {
                "service": W2,
                "uptime_sec": uptime,
                "grace_sec": grace_seconds,
            })
            return 0

        logs = service_logs(W2, WINDOW_MIN)
        m = parse_w2_health(logs)
        append_event("w2_health", {"window_min": WINDOW_MIN, **m})

        should_trip = (
            m["search_failures"] >= FAIL_THRESHOLD or
            m["restarts"] >= RESTART_THRESHOLD or
            m["hard_hits"] >= 1
        )

        if should_trip:
            reason = (
                f"trip: search_failures={m['search_failures']} "
                f"restarts={m['restarts']} hard_hits={m['hard_hits']}"
            )
            ok = stop_service(W2)
            state["breaker_open_until"] = now_ts + COOLDOWN_MIN * 60
            state["last_reason"] = reason
            state["last_action_at"] = now_iso()
            save_state(state)
            append_event("breaker_trip", {
                "service": W2,
                "reason": reason,
                "cooldown_min": COOLDOWN_MIN,
                "stop_ok": ok,
            })

    else:
        append_event("w2_not_running", {"auto_recover": AUTO_RECOVER_W2})

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
