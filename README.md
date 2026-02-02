# Discord Translate Bot (Python)

Supports three modes: **auto**, **mirror**, and **command**. Providers: **DeepSeek**, **OpenAI**, **Google Translate**, **Gemini**.

## Features
- Auto-translate in the same channel (optional channel allowlist)
- Mirror channels (source → target)
- Slash command translation
- Switch providers and modes at runtime
- Bilingual auto-switch for English/Chinese
- Per-user language overrides
- Automatic language detection beyond en/zh (when using auto source/target)

## Quick start
1) Copy example files:
   - config.json.example → config.json
   - .env.example → .env
2) Install dependencies:
   - `pip install -r requirements.txt`
3) Run the bot:
   - `python main.py`

## Key commands
- /set_mode auto|mirror|command
- /set_provider deepseek|openai|google|gemini
- /set_languages source target
  - source: auto|en|zh
   - target: auto|auto-bidir|en|zh
- /set_user_languages source target
- /clear_user_languages
- /my_languages
- /set_auto_channel enabled (toggles current channel for auto mode)
- /set_mirror #source #target
- /remove_mirror #source #target
- /translate text [target] [source]
- /status

## Notes on free hosting
Cloudflare Pages is **not** suitable (no long-running processes). For free-ish hosting:
- Self-host on your own PC or spare device
- Fly.io / Render / Railway (free tiers may be limited)
- Cloudflare Workers (paid after free tier)

## Deploy on Render (free worker)
1) Create a new Render account and connect your GitHub repo.
2) Choose "Background Worker" and select this repository.
3) Render will auto-detect [render.yaml](render.yaml).
4) Add environment variables in the Render dashboard (do not commit secrets):
   - DISCORD_TOKEN
   - DEEPSEEK_API_KEY (or OPENAI_API_KEY / GOOGLE_API_KEY)
5) Deploy. The bot will come online once the worker is running.

Your local .env files (including .env.gemini) are not used in Render.

## Provider keys
Set keys in .env:
- DeepSeek: DEEPSEEK_API_KEY
- OpenAI: OPENAI_API_KEY
- Google: GOOGLE_API_KEY
- Gemini: GEMINI_API_KEY

## Language behavior
Default is auto-bidir for English/Chinese:
- If message contains CJK characters → zh → en
- Otherwise → en → zh

You can override by `/set_languages` or `/translate`.

For broader auto detection, set source to `auto` and target to `auto`, and configure
`fallback_target_language` in config.
