# Front Row – turn Instagram DMs into video ideas

A small web app for content creators (business / tech audience). It connects to an Instagram
Professional account, pulls the DM threads from the last 7 days, lets you tick/untick messages, and
uses an OpenAI-compatible LLM to identify, deduplicate and summarise the viewers' questions and
suggestions into video ideas – each with a duplicate count and links back to the original messages.

## Run

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Open http://localhost:8000. If no LLM endpoint/key is configured yet you are sent to **Settings**.

## Settings

Everything is entered in the Settings page and stored in `data/settings.json` (git-ignored).

**LLM** – any OpenAI-compatible chat-completions endpoint: base URL (e.g. `https://api.openai.com/v1`,
`https://openrouter.ai/api/v1`, a local Ollama/vLLM server…), API key and model name.

**Instagram** – two options:

* *Log in with Instagram*: create a Meta app with the **Instagram API with Instagram Login** product,
  add `<public base URL>/api/instagram/callback` as a valid OAuth redirect URI (Meta requires https, so use
  e.g. ngrok when running locally), then enter App ID, App Secret and the public base URL and click
  **Log in with Instagram**. The account must be an Instagram Professional (Business or Creator) account.
* *Paste an access token* with the `instagram_business_basic` and `instagram_business_manage_messages`
  scopes (e.g. generated from the Meta app dashboard).

**Import DMs (no API)** – if Meta's Conversations API returns nothing for your account (e.g. the app is
still in Development mode), upload an Instagram *Download your information* export (Settings → Your
activity → Download your information → Messages, **JSON** format; zip or a single `message_1.json`),
or paste messages as `@username: text` lines with a blank line between threads. Imported threads go
through the same 7-day filter, checkboxes and summariser.

**Demo mode** – uses built-in sample threads so you can try the summariser without Instagram.

## How it works

* `GET /api/threads` – `me/conversations?platform=instagram` on `graph.instagram.com`, filtered to the last
  7 days (note: the Messaging API only returns text for the 20 most recent messages per conversation).
* `POST /api/summarise` – sends the selected viewer messages (creator replies are excluded) to the LLM
  with a prompt that asks for deduplicated questions/suggestions as JSON, each citing the message ids it
  was derived from. The UI renders each idea with its count and links every cited message back to the
  inbox view, where it is highlighted, plus a link to the sender's Instagram profile.
