#!/usr/bin/env python3
import argparse
import csv
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

import requests


def load_env(path: str) -> Dict[str, str]:
    env = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def clean(v: str) -> str:
    return (v or "").strip()


def score_agent(email: str, phone: str, is_new_licensee: bool, appointments_count: int) -> int:
    score = 0
    if email:
        score += 10
    if phone:
        score += 5
    if is_new_licensee:
        score += 30
    elif appointments_count <= 2:
        score += 15
    return score


def build_appointments(row: dict) -> List[dict]:
    out = []
    for i in range(1, 11):
        company = clean(row.get(f"appt_{i}_company", ""))
        naic = clean(row.get(f"appt_{i}_naic", ""))
        loa = clean(row.get(f"appt_{i}_loa", ""))
        appt_date = clean(row.get(f"appt_{i}_appt_date", ""))
        eff_date = clean(row.get(f"appt_{i}_eff_date", ""))
        exp_date = clean(row.get(f"appt_{i}_exp_date", ""))
        if company or naic:
            out.append(
                {
                    "company_name": company,
                    "naic_cocode": naic,
                    "license_type": "",
                    "line_of_authority": loa,
                    "appointment_date": appt_date,
                    "effective_date": eff_date,
                    "expiration_date": exp_date,
                }
            )
    return out


class SB:
    def __init__(self, url: str, key: str):
        self.base = url.rstrip("/") + "/rest/v1/"
        self.headers = {
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def get(self, table: str, params: dict):
        r = requests.get(self.base + table, params=params, headers=self.headers, timeout=60)
        r.raise_for_status()
        return r

    def post(self, table: str, data: list | dict):
        r = requests.post(self.base + table, headers={**self.headers, "Prefer": "return=representation"}, json=data, timeout=60)
        r.raise_for_status()
        return r

    def patch(self, table: str, filters: dict, data: dict):
        r = requests.patch(self.base + table, params=filters, headers={**self.headers, "Prefer": "return=representation"}, json=data, timeout=60)
        r.raise_for_status()
        return r


def fetch_existing_for_states(sb: SB, states: List[str]) -> Tuple[Dict[str, int], Dict[str, int]]:
    npn_to_id: Dict[str, int] = {}
    name_state_to_id: Dict[str, int] = {}

    for state in sorted(set(states)):
        offset = 0
        page = 1000
        while True:
            params = {
                "select": "id,npn,name,state",
                "state": f"eq.{state}",
                "offset": str(offset),
                "limit": str(page),
            }
            rows = sb.get("agents", params).json()
            if not rows:
                break
            for r in rows:
                aid = r.get("id")
                npn = clean(r.get("npn", ""))
                name = clean(r.get("name", ""))
                st = clean(r.get("state", ""))
                if npn:
                    npn_to_id[npn] = aid
                if name and st:
                    name_state_to_id[f"{name}||{st}"] = aid
            if len(rows) < page:
                break
            offset += page

    return npn_to_id, name_state_to_id


def read_states(files: List[str]) -> List[str]:
    states = []
    for fp in files:
        with open(fp, "r", encoding="utf-8", errors="replace", newline="") as f:
            dr = csv.DictReader(f)
            for row in dr:
                st = clean(row.get("state", ""))
                if st:
                    states.append(st)
    return states


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", default=".env.worker1")
    ap.add_argument("files", nargs="+")
    args = ap.parse_args()

    env = load_env(args.env)
    sb = SB(env["SUPABASE_URL"], env["SUPABASE_KEY"])

    files = [str(Path(f).expanduser()) for f in args.files]
    for f in files:
        if not Path(f).exists():
            raise FileNotFoundError(f)

    states = read_states(files)
    npn_to_id, name_state_to_id = fetch_existing_for_states(sb, states)

    stats = {
        "files": len(files),
        "rows_total": 0,
        "inserted": 0,
        "updated": 0,
        "skipped": 0,
        "errors": 0,
    }

    for fp in files:
        with open(fp, "r", encoding="utf-8", errors="replace", newline="") as f:
            dr = csv.DictReader(f)
            for row in dr:
                stats["rows_total"] += 1
                try:
                    name = clean(row.get("name", ""))
                    state = clean(row.get("state", ""))
                    if not name or not state:
                        stats["skipped"] += 1
                        continue

                    npn = clean(row.get("npn", ""))
                    email = clean(row.get("email", ""))
                    phone = clean(row.get("phone", ""))
                    appts = build_appointments(row)
                    appointments_count = len(appts)
                    is_new_licensee = appointments_count == 0

                    agent_data = {
                        "name": name,
                        "npn": npn or None,
                        "email": email,
                        "phone": phone,
                        "state": state,
                        "business_address": clean(row.get("business_address", "")),
                        "loa": clean(row.get("loa", "Life")) or "Life",
                        "license_type": "Insurance Producer",
                        "license_status": clean(row.get("license_status", "Active")) or "Active",
                        "license_expiration": clean(row.get("license_expiration", "")),
                        "effective_date": clean(row.get("effective_date", "")),
                        "appointments": appts,
                        "appointments_list": appts,
                        "appointments_count": appointments_count,
                        "is_new_licensee": is_new_licensee,
                        "pipeline_stage": "scraped",
                        "email_status": "pending",
                        "score": score_agent(email, phone, is_new_licensee, appointments_count),
                        "opted_out": False,
                        "scraped_at": clean(row.get("scraped_at", "")) or now_iso(),
                    }

                    agent_id = None
                    if npn and npn in npn_to_id:
                        agent_id = npn_to_id[npn]
                    else:
                        key = f"{name}||{state}"
                        agent_id = name_state_to_id.get(key)

                    if agent_id:
                        sb.patch("agents", {"id": f"eq.{agent_id}"}, agent_data)
                        stats["updated"] += 1
                    else:
                        agent_data["first_scraped_at"] = now_iso()
                        inserted = sb.post("agents", agent_data).json()
                        new_id = inserted[0]["id"]
                        if npn:
                            npn_to_id[npn] = new_id
                        name_state_to_id[f"{name}||{state}"] = new_id
                        stats["inserted"] += 1

                except Exception:
                    stats["errors"] += 1

                if stats["rows_total"] % 1000 == 0:
                    print(json.dumps({"progress": stats["rows_total"], **stats}))

    print(json.dumps({"done": True, **stats}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
