"""
Shared lib — server-side (uses refresh_token + curl for Gmail API).
"""
import os, json, subprocess, pathlib, re, time
from typing import Optional, Tuple, Dict, List

HOME = pathlib.Path("/home/david")
NANOCLAW = HOME / "nanoclaw"
DOTENV = NANOCLAW / ".env"
GMAIL_CREDS = HOME / ".gmail-mcp" / "credentials.json"
GMAIL_KEYS = HOME / ".gmail-mcp" / "gcp-oauth.keys.json"

# ---------- env ----------

def read_env_var(key: str) -> Optional[str]:
    try:
        if not DOTENV.exists():
            return None
        for line in DOTENV.read_text().splitlines():
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except (PermissionError, OSError):
        return None
    return None

# ---------- curl helpers ----------

def curl_post(url: str, data, timeout: int = 20, headers=None) -> Tuple[int, str]:
    """POST either form-encoded (dict) or raw JSON (str). Returns (http_code, body)."""
    cmd = ["curl", "-s", "-w", "\n__HTTP__:%{http_code}", "--max-time", str(timeout),
           "-X", "POST", url]
    for k, v in (headers or {}).items():
        cmd += ["-H", f"{k}: {v}"]
    if isinstance(data, dict):
        for k, v in data.items():
            cmd += ["--data-urlencode", f"{k}={v}"]
    else:
        needs_ct = not any(h.lower() == "content-type" for h in (headers or {}))
        if needs_ct:
            cmd += ["-H", "Content-Type: application/json"]
        cmd += ["-d", data]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 5)
        out = r.stdout
        code = 0
        if "\n__HTTP__:" in out:
            body, _, codepart = out.rpartition("\n__HTTP__:")
            out = body
            try:
                code = int(codepart.strip())
            except Exception:
                pass
        return code, out
    except Exception as e:
        return 0, f"{type(e).__name__}: {e}"

def curl_get(url: str, headers=None, timeout: int = 20) -> Tuple[int, str]:
    cmd = ["curl", "-s", "-w", "\n__HTTP__:%{http_code}", "--max-time", str(timeout), url]
    for k, v in (headers or {}).items():
        cmd += ["-H", f"{k}: {v}"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 5)
        out = r.stdout
        code = 0
        if "\n__HTTP__:" in out:
            body, _, codepart = out.rpartition("\n__HTTP__:")
            out = body
            try:
                code = int(codepart.strip())
            except Exception:
                pass
        return code, out
    except Exception as e:
        return 0, f"{type(e).__name__}: {e}"

# ---------- Gmail auth ----------

_ACCESS_TOKEN = {"v": None, "expires_at": 0}


def _load_creds() -> Dict:
    return json.loads(GMAIL_CREDS.read_text())

def _save_creds(c: Dict):
    GMAIL_CREDS.write_text(json.dumps(c, indent=2))

def _load_keys() -> Dict:
    k = json.loads(GMAIL_KEYS.read_text())
    return k.get("installed") or k.get("web") or k

def gmail_access_token() -> str:
    now = time.time()
    if _ACCESS_TOKEN["v"] and _ACCESS_TOKEN["expires_at"] > now + 60:
        return _ACCESS_TOKEN["v"]
    creds = _load_creds()
    exp_ms = creds.get("expiry_date", 0)
    if exp_ms and exp_ms / 1000 > now + 60 and creds.get("access_token"):
        _ACCESS_TOKEN["v"] = creds["access_token"]
        _ACCESS_TOKEN["expires_at"] = exp_ms / 1000
        return creds["access_token"]

    keys = _load_keys()
    code, body = curl_post("https://oauth2.googleapis.com/token", {
        "client_id": keys["client_id"],
        "client_secret": keys["client_secret"],
        "refresh_token": creds["refresh_token"],
        "grant_type": "refresh_token",
    })
    if code != 200:
        raise RuntimeError(f"gmail refresh failed: {code} {body[:300]}")
    r = json.loads(body)
    creds["access_token"] = r["access_token"]
    creds["expiry_date"] = int((now + r.get("expires_in", 3500)) * 1000)
    _save_creds(creds)
    _ACCESS_TOKEN["v"] = creds["access_token"]
    _ACCESS_TOKEN["expires_at"] = creds["expiry_date"] / 1000
    return creds["access_token"]

# ---------- Gmail API ----------

def _auth_headers() -> Dict:
    return {"Authorization": f"Bearer {gmail_access_token()}"}

def gmail_search(query: str, max_results: int = 100) -> List[Dict]:
    import urllib.parse as up
    url = (
        f"https://gmail.googleapis.com/gmail/v1/users/me/messages"
        f"?maxResults={max_results}&q={up.quote(query)}"
    )
    code, body = curl_get(url, headers=_auth_headers())
    if code != 200:
        raise RuntimeError(f"gmail search failed: {code} {body[:300]}")
    d = json.loads(body)
    ids = [m["id"] for m in d.get("messages", [])]
    results = []
    for mid in ids:
        url = (
            f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{mid}"
            f"?format=metadata&metadataHeaders=From&metadataHeaders=Subject&metadataHeaders=Date"
        )
        code, body = curl_get(url, headers=_auth_headers())
        if code != 200:
            continue
        m = json.loads(body)
        headers = {h["name"].lower(): h["value"] for h in m.get("payload", {}).get("headers", [])}
        results.append({
            "id": m["id"],
            "threadId": m.get("threadId"),
            "from": headers.get("from", ""),
            "subject": headers.get("subject", ""),
            "date": headers.get("date", ""),
            "snippet": m.get("snippet", ""),
            "labels": m.get("labelIds", []),
        })
    return results


def _batch_modify(ids: List[str], payload_fn) -> int:
    if not ids:
        return 0
    done = 0
    for i in range(0, len(ids), 100):
        chunk = list(ids[i:i+100])
        payload = json.dumps(payload_fn(chunk))
        code, body = curl_post(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/batchModify",
            payload, headers=_auth_headers(),
        )
        if code in (200, 204):
            done += len(chunk)
            continue
        _ACCESS_TOKEN["expires_at"] = 0
        code, body = curl_post(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/batchModify",
            payload, headers=_auth_headers(),
        )
        if code in (200, 204):
            done += len(chunk)
        else:
            raise RuntimeError(f"batchModify failed: {code} {body[:200]}")
    return done


def gmail_archive_many(ids: List[str]) -> int:
    return _batch_modify(ids, lambda chunk: {"ids": chunk, "removeLabelIds": ["INBOX"]})


def gmail_unarchive_many(ids: List[str]) -> int:
    return _batch_modify(ids, lambda chunk: {"ids": chunk, "addLabelIds": ["INBOX"]})


def gmail_read(msg_id: str) -> str:
    import base64, re as _re
    url = f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{msg_id}?format=full"
    code, body = curl_get(url, headers=_auth_headers())
    if code != 200:
        return f"[read error {code}]"
    try:
        d = json.loads(body)
    except Exception as e:
        return f"[parse error {e}]"

    acc = []

    def collect(part):
        mime = part.get("mimeType", "")
        b = part.get("body", {})
        if "data" in b and mime in ("text/plain", "text/html"):
            try:
                raw = base64.urlsafe_b64decode(
                    b["data"] + "=" * (4 - len(b["data"]) % 4)
                ).decode("utf-8", "ignore")
                acc.append((mime, raw))
            except Exception:
                pass
        for p2 in part.get("parts", []):
            collect(p2)

    collect(d.get("payload", {}))
    if not acc:
        return ""
    plain = [r for m, r in acc if m == "text/plain"]
    if plain:
        text = "\n".join(plain)
    else:
        html = "\n".join(r for _, r in acc)
        text = _re.sub(r"<style[^>]*>.*?</style>", " ", html, flags=_re.S | _re.I)
        text = _re.sub(r"<script[^>]*>.*?</script>", " ", text, flags=_re.S | _re.I)
        text = _re.sub(r"<[^>]+>", " ", text)
        text = _re.sub(r"&\w+;", " ", text)
    text = _re.sub(r"\s+", " ", text).strip()
    return text


def gmail_reply(msg_id: str, body: str) -> Dict:
    import base64
    url = (
        f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{msg_id}"
        f"?format=metadata&metadataHeaders=From&metadataHeaders=Subject"
        f"&metadataHeaders=Message-ID&metadataHeaders=References"
    )
    code, resp = curl_get(url, headers=_auth_headers())
    if code != 200:
        raise RuntimeError(f"fetch for reply failed: {code}")
    d = json.loads(resp)
    headers = {h["name"].lower(): h["value"] for h in d.get("payload", {}).get("headers", [])}
    to_addr = headers.get("from", "")
    subject = headers.get("subject", "")
    if not subject.lower().startswith("re:"):
        subject = "Re: " + subject
    message_id_header = headers.get("message-id", "")
    references = headers.get("references", "")
    refs_new = (references + " " + message_id_header).strip() if references else message_id_header

    raw = (
        f"To: {to_addr}\r\n"
        f"Subject: {subject}\r\n"
        f"In-Reply-To: {message_id_header}\r\n"
        f"References: {refs_new}\r\n"
        f"Content-Type: text/plain; charset=utf-8\r\n"
        f"\r\n"
        f"{body}\r\n"
    )
    encoded = base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")
    payload = json.dumps({"raw": encoded, "threadId": d["threadId"]})
    code, resp = curl_post(
        "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
        payload, headers=_auth_headers(),
    )
    if code not in (200, 204):
        raise RuntimeError(f"send failed: {code} {resp[:300]}")
    return json.loads(resp)

# ---------- Telegram ----------

def _get_bot_token(bot_env_key: str = "INBOX_BRIEF_BOT_TOKEN") -> str:
    token = os.getenv(bot_env_key) or os.getenv("TELEGRAM_BOT_TOKEN")
    if token:
        return token
    token = read_env_var(bot_env_key) or read_env_var("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError(f"no {bot_env_key}")
    return token


def telegram_send(chat_id: str, text: str, parse_mode: str = "", reply_to_msg=None,
                  bot_env_key: str = "INBOX_BRIEF_BOT_TOKEN") -> Dict:
    token = _get_bot_token(bot_env_key)
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = {"chat_id": chat_id, "text": text, "disable_web_page_preview": "true"}
    if parse_mode:
        data["parse_mode"] = parse_mode
    if reply_to_msg:
        data["reply_to_message_id"] = str(reply_to_msg)
    code, resp = curl_post(url, data)
    try:
        d = json.loads(resp)
    except Exception:
        raise RuntimeError(f"tg send unparseable: code={code} body={resp[:300]}")
    if not d.get("ok"):
        raise RuntimeError(f"tg send rejected: {d}")
    return d["result"]


def telegram_get_updates(offset=None, timeout: int = 10,
                         bot_env_key: str = "INBOX_BRIEF_BOT_TOKEN") -> List[Dict]:
    token = _get_bot_token(bot_env_key)
    params = [f"timeout={timeout}"]
    if offset is not None:
        params.append(f"offset={offset}")
    url = f"https://api.telegram.org/bot{token}/getUpdates?{'&'.join(params)}"
    code, resp = curl_get(url, timeout=timeout + 5)
    try:
        d = json.loads(resp)
    except Exception:
        raise RuntimeError(f"tg updates unparseable: code={code} body={resp[:300]}")
    if not d.get("ok"):
        raise RuntimeError(f"tg updates rejected: {d}")
    return d.get("result", [])

# ---------- formatting ----------

def clean_from(f: str, max_len: int = 30) -> str:
    if not f:
        return ""
    m = re.match(r'"?(.+?)"?\s*<', f)
    name = m.group(1).strip() if m else f.split("@")[0].strip().strip('"')
    return name[:max_len]

def trunc(s: str, n: int) -> str:
    s = (s or "").strip().replace("\n", " ")
    return s if len(s) <= n else s[:n-1] + "…"
