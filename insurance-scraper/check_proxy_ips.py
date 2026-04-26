#!/usr/bin/env python3
"""
Check effective egress IP for each worker env file.

Usage:
  python3 check_proxy_ips.py .env.worker1 .env.worker2
"""

import os
import sys
import requests
from dotenv import dotenv_values

IP_CHECK_URL = "https://api.ipify.org"


def check_env(path: str):
    env = dotenv_values(path)
    proxy = env.get("PROXY_URL", "").strip()
    worker = env.get("WORKER_ID", os.path.basename(path))

    if not proxy:
        return worker, path, None, "MISSING_PROXY_URL"

    proxies = {"http": proxy, "https": proxy}
    try:
        r = requests.get(IP_CHECK_URL, proxies=proxies, timeout=20)
        r.raise_for_status()
        return worker, path, r.text.strip(), None
    except Exception as e:
        return worker, path, None, str(e)


def main():
    paths = sys.argv[1:]
    if not paths:
        print("Usage: python3 check_proxy_ips.py .env.worker1 .env.worker2 [...]")
        sys.exit(1)

    print("Worker proxy IP check")
    print("=" * 60)
    ips = {}
    for p in paths:
        worker, path, ip, err = check_env(p)
        if err:
            print(f"{worker:<16} {path:<20} ERROR: {err}")
            continue
        ips.setdefault(ip, []).append(worker)
        print(f"{worker:<16} {path:<20} IP: {ip}")

    print("\nDistinct IP summary")
    print("=" * 60)
    for ip, workers in ips.items():
        print(f"{ip}: {', '.join(workers)}")

    reused = {ip: workers for ip, workers in ips.items() if len(workers) > 1}
    if reused:
        print("\nWARNING: some workers share the same IP")
        for ip, workers in reused.items():
            print(f"  {ip}: {', '.join(workers)}")
        sys.exit(2)


if __name__ == "__main__":
    main()
