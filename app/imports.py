"""Import DM threads without the Graph API.

Two sources:
- an Instagram "Download your information" export (zip or a single message_N.json), JSON format
- plain text pasted by the user: `@username: message` per line, blank line between threads
"""

import hashlib
import io
import json
import re
import zipfile
from collections import Counter
from datetime import datetime, timedelta, timezone

from .models import Message, Thread
from .settings import DATA_DIR

IMPORT_PATH = DATA_DIR / "imported_threads.json"


class ImportError_(Exception):
    pass


def _fix_mojibake(s: str) -> str:
    # Meta exports encode UTF-8 bytes as latin-1 escapes ("\u00e2\u0080\u0099" for ’)
    try:
        return s.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s


def _mid(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:16]


# ---------- Download-your-information export ----------

def _dyi_threads_from_json(doc: dict, source_path: str) -> dict | None:
    if not isinstance(doc, dict) or "messages" not in doc or "participants" not in doc:
        return None
    return {
        "path": source_path,
        "title": _fix_mojibake(doc.get("title", "")),
        "participants": [_fix_mojibake(p.get("name", "")) for p in doc.get("participants", [])],
        "messages": [
            {
                "sender": _fix_mojibake(m.get("sender_name", "")),
                "ts": m.get("timestamp_ms", 0),
                "text": _fix_mojibake(m.get("content", "")),
            }
            for m in doc.get("messages", [])
            if m.get("content")
        ],
    }


def _load_dyi_docs(data: bytes) -> list[dict]:
    docs: list[dict] = []
    if zipfile.is_zipfile(io.BytesIO(data)):
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for name in zf.namelist():
                if "/inbox/" in name and re.search(r"message_\d+\.json$", name):
                    try:
                        raw = json.loads(zf.read(name))
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        continue
                    d = _dyi_threads_from_json(raw, name)
                    if d:
                        docs.append(d)
    else:
        try:
            raw = json.loads(data)
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise ImportError_("File is neither a zip nor a JSON file.")
        d = _dyi_threads_from_json(raw, "upload.json")
        if d:
            docs.append(d)
    if not docs:
        raise ImportError_(
            "No DM threads found. Expected an Instagram 'Download your information' export in JSON format "
            "(zip containing messages/inbox/*/message_1.json) or one of those message_1.json files."
        )
    return docs


def parse_dyi(data: bytes, owner_name: str = "") -> list[Thread]:
    docs = _load_dyi_docs(data)
    # The account owner is the participant present in every thread; fall back to the most common one.
    if not owner_name:
        counts = Counter(p for d in docs for p in set(d["participants"]))
        owner_name = counts.most_common(1)[0][0] if counts else ""

    # Same thread may be split into message_1.json, message_2.json ... under one folder
    grouped: dict[str, dict] = {}
    for d in docs:
        key = d["path"].rsplit("/", 1)[0]
        g = grouped.setdefault(key, {"title": d["title"], "participants": d["participants"], "messages": []})
        g["messages"].extend(d["messages"])

    threads: list[Thread] = []
    for key, g in grouped.items():
        others = [p for p in g["participants"] if p != owner_name] or g["participants"]
        if len(others) != 1:
            continue  # skip group chats
        other = others[0]
        # folder is "<username>_<numeric id>"; the JSON itself only carries display names
        folder = key.rsplit("/", 1)[-1]
        other_username = re.sub(r"_\d+$", "", folder) if folder and folder != "upload.json" else ""
        tid = "dyi-" + _mid(key)
        msgs: list[Message] = []
        for m in sorted(g["messages"], key=lambda x: x["ts"]):
            if not m["text"].strip():
                continue
            from_me = m["sender"] == owner_name
            msgs.append(
                Message(
                    id="m-" + _mid(tid, str(m["ts"]), m["text"]),
                    thread_id=tid,
                    text=m["text"],
                    created_time=datetime.fromtimestamp(m["ts"] / 1000, tz=timezone.utc),
                    sender_id=m["sender"],
                    sender_username=(other_username or m["sender"]) if not from_me else m["sender"],
                    from_me=from_me,
                )
            )
        if not msgs:
            continue
        threads.append(
            Thread(
                id=tid,
                updated_time=max(m.created_time for m in msgs),
                participant_id=other,
                participant_username=other_username,
                messages=msgs,
            )
        )
    threads.sort(key=lambda t: t.updated_time, reverse=True)
    return threads


# ---------- pasted text ----------

_LINE = re.compile(r"^\s*@?([A-Za-z0-9._]+)\s*[:\-–]\s*(.+)$")


def parse_text(text: str, owner_username: str = "") -> list[Thread]:
    """`@user: message` per line; blank lines separate threads; lines from `owner_username`
    (or 'me'/'you') are treated as the creator's own replies."""
    now = datetime.now(timezone.utc)
    me = {owner_username.lower(), "me", "you"} - {""}
    threads: list[Thread] = []
    blocks = [b for b in re.split(r"\n\s*\n", text.strip()) if b.strip()]
    for bi, block in enumerate(blocks):
        msgs: list[Message] = []
        tid = "paste-" + _mid(str(bi), block)
        other = ""
        for li, line in enumerate(block.splitlines()):
            m = _LINE.match(line)
            if not m:
                if msgs:
                    msgs[-1].text += "\n" + line.strip()
                continue
            user, body = m.group(1), m.group(2).strip()
            from_me = user.lower() in me
            if not from_me and not other:
                other = user
            msgs.append(
                Message(
                    id="m-" + _mid(tid, str(li), body),
                    thread_id=tid,
                    text=body,
                    created_time=now - timedelta(minutes=len(blocks) - bi, seconds=-li),
                    sender_id=user,
                    sender_username=user,
                    from_me=from_me,
                )
            )
        if not msgs:
            continue
        threads.append(
            Thread(
                id=tid,
                updated_time=max(m.created_time for m in msgs),
                participant_id=other or msgs[0].sender_id,
                participant_username=other or msgs[0].sender_username,
                messages=msgs,
            )
        )
    if not threads:
        raise ImportError_("No messages recognised. Use one `@username: message` per line, blank line between threads.")
    return threads


# ---------- persistence ----------

def save_imported(threads: list[Thread]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    IMPORT_PATH.write_text(json.dumps([t.model_dump(mode="json") for t in threads]))


def load_imported() -> list[Thread]:
    if not IMPORT_PATH.exists():
        return []
    return [Thread.model_validate(t) for t in json.loads(IMPORT_PATH.read_text())]


def clear_imported() -> None:
    if IMPORT_PATH.exists():
        IMPORT_PATH.unlink()


def within_days(threads: list[Thread], days: int) -> list[Thread]:
    if days <= 0:
        return threads
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    out: list[Thread] = []
    for t in threads:
        msgs = [m for m in t.messages if m.created_time >= cutoff]
        if msgs:
            out.append(t.model_copy(update={"messages": msgs}))
    return out
