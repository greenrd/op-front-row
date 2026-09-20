"""Instagram Messaging API client (Instagram API with Instagram Login)."""

import asyncio
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx

from .models import Message, Thread
from .settings import Settings

GRAPH = "https://graph.instagram.com/v21.0"
FB_GRAPH = "https://graph.facebook.com/v21.0"
OAUTH_AUTHORIZE = "https://www.instagram.com/oauth/authorize"
OAUTH_TOKEN = "https://api.instagram.com/oauth/access_token"
SCOPES = "instagram_business_basic,instagram_business_manage_messages"

MESSAGE_FIELDS = "id,created_time,from,message"


class InstagramError(Exception):
    pass


def redirect_uri(settings: Settings) -> str:
    return settings.public_base_url.rstrip("/") + "/api/instagram/callback"


def authorize_url(settings: Settings) -> str:
    params = {
        "client_id": settings.ig_app_id,
        "redirect_uri": redirect_uri(settings),
        "response_type": "code",
        "scope": SCOPES,
        "force_reauth": "true",
    }
    return f"{OAUTH_AUTHORIZE}?{urlencode(params)}"


async def exchange_code(settings: Settings, code: str) -> str:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            OAUTH_TOKEN,
            data={
                "client_id": settings.ig_app_id,
                "client_secret": settings.ig_app_secret,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri(settings),
                "code": code,
            },
        )
        _raise(resp)
        short_token = resp.json()["access_token"]

        resp = await client.get(
            f"{GRAPH}/access_token",
            params={
                "grant_type": "ig_exchange_token",
                "client_secret": settings.ig_app_secret,
                "access_token": short_token,
            },
        )
        if resp.status_code != 200:
            return short_token
        return resp.json()["access_token"]


class Account:
    """Resolved messaging endpoint for a token.

    Instagram Login tokens (``IGAA…``) talk to graph.instagram.com as ``me``.
    Facebook Login tokens (``EAA…``) talk to graph.facebook.com via the Facebook Page linked to the IG account.
    """

    def __init__(self, base: str, node: str, token: str, ig_user_id: str, username: str):
        self.base = base
        self.node = node
        self.token = token
        self.ig_user_id = ig_user_id
        self.username = username


async def resolve_account(client: httpx.AsyncClient, token: str) -> Account:
    if token.startswith("IG"):
        resp = await client.get(f"{GRAPH}/me", params={"fields": "user_id,username", "access_token": token})
        _raise(resp)
        me = resp.json()
        return Account(GRAPH, "me", token, str(me.get("user_id") or me.get("id") or ""), me.get("username", ""))

    # Facebook-issued token: find a Page with a linked Instagram professional account.
    page_fields = "id,name,access_token,instagram_business_account{id,username}"
    resp = await client.get(f"{FB_GRAPH}/me/accounts", params={"fields": page_fields, "access_token": token})
    pages = resp.json().get("data", []) if resp.status_code == 200 else []
    if not pages:
        # Maybe it is already a Page token.
        resp = await client.get(
            f"{FB_GRAPH}/me", params={"fields": "id,instagram_business_account{id,username}", "access_token": token}
        )
        me = resp.json() if resp.status_code == 200 else {}
        if "instagram_business_account" in me:
            pages = [me]
    linked = [p for p in pages if p.get("instagram_business_account")]
    if not linked:
        raise InstagramError(
            "This is a Facebook token, but no Facebook Page with a linked Instagram professional account is "
            "accessible to it. Either assign the Page to this user/system user in Meta Business settings, or "
            "generate an Instagram Login token (starts with IGAA) from 'API setup with Instagram login'."
        )
    page = linked[0]
    ig = page["instagram_business_account"]
    return Account(FB_GRAPH, page["id"], page.get("access_token") or token, str(ig["id"]), ig.get("username", ""))


async def fetch_profile(token: str) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        acct = await resolve_account(client, token)
        return {"user_id": acct.ig_user_id, "username": acct.username}


async def fetch_threads(token: str, days: int = 7) -> list[Thread]:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    threads: list[Thread] = []
    async with httpx.AsyncClient(timeout=60) as client:
        acct = await resolve_account(client, token)
        my_id = acct.ig_user_id
        token = acct.token

        # One request per page with messages nested; if Meta rejects the payload size
        # (code 1 "reduce the amount of data") fall back to fetching messages per conversation.
        url: str | None = f"{acct.base}/{acct.node}/conversations"
        nested_fields = f"id,updated_time,participants{{id,username}},messages.limit(50){{{MESSAGE_FIELDS}}}"
        flat_fields = "id,updated_time,participants{id,username}"
        params: dict | None = {"platform": "instagram", "fields": nested_fields, "limit": 50, "access_token": token}
        while url:
            resp = await client.get(url, params=params)
            if _is_reduce_data_error(resp) and params is not None:
                params.update(fields=flat_fields, limit=10)
                resp = await client.get(url, params=params)
            _raise(resp)
            body = resp.json()
            recent = []
            stop = False
            for conv in body.get("data", []):
                updated = _parse_time(conv.get("updated_time"))
                if updated and updated < since:
                    stop = True
                    continue
                recent.append(conv)
            for thread in await asyncio.gather(*(_build_thread(client, acct, c, my_id, since) for c in recent)):
                if thread.messages:
                    threads.append(thread)
            next_url = body.get("paging", {}).get("next")
            url = None if stop else next_url
            params = None  # `next` already carries the query string
    threads.sort(key=lambda t: t.updated_time, reverse=True)
    return threads


async def _build_thread(client: httpx.AsyncClient, acct: Account, conv: dict, my_id: str, since: datetime) -> Thread:
    participants = [
        {"id": str(p.get("id", "")), "username": p.get("username", "")}
        for p in conv.get("participants", {}).get("data", [])
    ]
    others = [p for p in participants if p["id"] != my_id] or participants
    counterpart = others[0] if others else {"id": "", "username": "unknown"}

    raw_messages = conv.get("messages", {}).get("data")
    if raw_messages is None:
        raw_messages = await _fetch_messages(client, acct, conv["id"])

    messages: list[Message] = []
    for m in raw_messages:
        created = _parse_time(m.get("created_time"))
        if not created or created < since:
            continue
        text = m.get("message") or ""
        if not text.strip():
            continue
        sender = m.get("from", {}) or {}
        sender_id = str(sender.get("id", ""))
        messages.append(
            Message(
                id=m["id"],
                thread_id=conv["id"],
                text=text,
                created_time=created,
                sender_id=sender_id,
                sender_username=sender.get("username", ""),
                from_me=bool(my_id) and sender_id == my_id,
            )
        )
    messages.sort(key=lambda m: m.created_time)
    return Thread(
        id=conv["id"],
        updated_time=_parse_time(conv.get("updated_time")) or (messages[-1].created_time if messages else since),
        participant_id=counterpart["id"],
        participant_username=counterpart["username"],
        messages=messages,
    )


async def _fetch_messages(client: httpx.AsyncClient, acct: Account, conv_id: str) -> list[dict]:
    """Messages of one conversation (fallback when they could not be nested in the conversations call)."""
    resp = await client.get(
        f"{acct.base}/{conv_id}/messages", params={"fields": MESSAGE_FIELDS, "limit": 50, "access_token": acct.token}
    )
    if resp.status_code == 200:
        return resp.json().get("data", [])
    if _is_reduce_data_error(resp):
        raise InstagramError(
            "Meta refused to return the messages of a conversation (code 1: \"Please reduce the amount of data\"), "
            "For Facebook-issued tokens this usually means the token lacks the "
            "pages_manage_metadata permission or was not issued to a user/system user with the Messaging task on "
            "the linked Page. Regenerate the token with instagram_basic, instagram_manage_messages, "
            "pages_manage_metadata, pages_read_engagement and pages_messaging."
        )
    _raise(resp)
    return []


def _is_reduce_data_error(resp: httpx.Response) -> bool:
    if resp.status_code < 400:
        return False
    try:
        err = resp.json().get("error", {})
    except ValueError:
        return False
    return err.get("code") == 1 and "reduce the amount of data" in (err.get("message") or "")


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    # Graph API returns e.g. 2024-05-01T12:34:56+0000
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _raise(resp: httpx.Response) -> None:
    if resp.status_code >= 400:
        try:
            err = resp.json().get("error", {})
            msg = err.get("message") or resp.text
        except ValueError:
            msg = resp.text
        raise InstagramError(f"Instagram API error ({resp.status_code}): {msg}")
