# VPKN — Telegram AI Assistant Bot

A personal Telegram bot that acts like Claude/ChatGPT but also generates **PDF documents** and **printable flyers** on demand. Built for [@vpkn_40733511_bot](https://t.me/vpkn_40733511_bot).

## What it does

- **Chat** — talk to it like ChatGPT/Claude. Conversation history is remembered per user. Powered by Google Gemini.
- **`/pdf <description>`** — generates a structured PDF document on the topic. Title, sections, bullets, callouts — professional layout, full Unicode (Russian/Cyrillic supported).
- **`/flyer <description>`** — Gemini designs a colorful flyer in HTML+CSS, WeasyPrint renders it to A4 PDF. Ready to print or send to a client.
- **`/image <description>`** — generates an image via Gemini 2.5 Flash Image.
- **`/reset`** — clear conversation memory.
- **`/help`** — list of commands.

## Architecture

```
Telegram ─► python-telegram-bot ─► handlers.py
                                    ├─► ai.py        (Google Gemini API)
                                    ├─► pdf_gen.py   (ReportLab + WeasyPrint)
                                    └─► storage.py   (per-chat history on disk)
```

Two run modes:

- **Long-polling** for local dev — no public URL needed.
- **Webhook** for production — set `WEBHOOK_BASE_URL` (or rely on `RENDER_EXTERNAL_HOSTNAME` which Render injects automatically) and the bot will register a Telegram webhook and listen on `0.0.0.0:$PORT`.

## Local development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# WeasyPrint needs system libraries (Pango, Cairo). On Debian/Ubuntu:
sudo apt-get install -y libpango-1.0-0 libpangoft2-1.0-0 \
    libharfbuzz0b libcairo2 libgdk-pixbuf-2.0-0 \
    shared-mime-info fonts-dejavu fonts-noto

cp .env.example .env
# fill in TELEGRAM_BOT_TOKEN and GEMINI_API_KEY

python bot.py
```

The bot will start in long-polling mode. Open Telegram, find your bot, send `/start`.

## Deploy to Render (free, 24/7)

1. **Create a GitHub repo** for this code (e.g. `vpkn-bot`).
2. Push this code to it.
3. Sign up at [render.com](https://render.com) with Google.
4. **New** → **Blueprint** → connect your repo. Render reads `render.yaml` and creates the service.
5. After the first build, open the service → **Environment** → set:
   - `TELEGRAM_BOT_TOKEN` — from [@BotFather](https://t.me/BotFather)
   - `GEMINI_API_KEY` — from [aistudio.google.com/apikey](https://aistudio.google.com/apikey)
6. Save → Render redeploys. The bot is live.

Render free tier sleeps after 15 minutes of inactivity, but Telegram webhooks wake the service on the first incoming message (cold-start ~30 s). For always-on, upgrade to Starter or deploy to [Koyeb](https://koyeb.com) free tier (no card, no sleep).

## Deploy to Koyeb (always-on free, no card)

1. Push code to GitHub.
2. Sign up at [koyeb.com](https://koyeb.com) with GitHub.
3. **Create Service** → **GitHub** → select repo.
4. Builder: **Dockerfile**.
5. Add env vars: `TELEGRAM_BOT_TOKEN`, `GEMINI_API_KEY`, `WEBHOOK_SECRET` (random string), `DATA_DIR=/tmp/bot_data`.
6. Instance: **Free** (Eco, 0.1 vCPU, 256 MB).
7. Deploy.

Koyeb sets a public URL like `https://<name>-<org>.koyeb.app` — the bot picks it up via the `WEBHOOK_BASE_URL` env var (set this manually to that URL, e.g. on the Environment tab).

## Configuration

All config is via environment variables (see `.env.example`):

| Variable | Required | Default | Notes |
| --- | --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` | yes | — | From @BotFather |
| `GEMINI_API_KEY` | yes | — | From aistudio.google.com/apikey |
| `GEMINI_MODEL` | no | `gemini-flash-latest` | Chat + document model |
| `GEMINI_IMAGE_MODEL` | no | `gemini-2.5-flash-image` | Used by `/image` |
| `WEBHOOK_BASE_URL` | only in prod | `${RENDER_EXTERNAL_HOSTNAME}` if set | Empty → polling mode |
| `WEBHOOK_SECRET` | recommended | auto-generated | Telegram secret-token validation |
| `PORT` | no | `8080` | HTTP port (Render/Koyeb inject this) |
| `DATA_DIR` | no | `bot_data` | Where chat histories are stored |
| `LOG_LEVEL` | no | `INFO` | Standard Python logging levels |

## Files

- `bot.py` — entrypoint; picks polling vs webhook based on env.
- `app/config.py` — environment-driven config.
- `app/ai.py` — Gemini wrapper (chat, structured documents, flyer HTML, image gen).
- `app/pdf_gen.py` — ReportLab document renderer + WeasyPrint flyer renderer.
- `app/storage.py` — per-chat conversation memory (JSON on disk).
- `app/handlers.py` — Telegram command handlers.
- `Dockerfile` — production image with all WeasyPrint system deps.
- `render.yaml` — Render Blueprint.
- `requirements.txt` — Python dependencies.

## License

Personal project. Use it however you like.
