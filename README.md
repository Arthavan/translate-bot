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

## Deploy on Wispbyte (free, 24/7)

1) Sign up at https://wispbyte.com/client (completely free, no credit card)
2) Create a new Discord Bot project
3) Upload your bot files:
   - Download/clone from https://github.com/Arthavan/translate-bot
   - Upload the files to Wispbyte dashboard
4) Set environment variables in the dashboard:
   - `DISCORD_TOKEN` = your bot token
   - `GEMINI_API_KEY` = your Gemini API key
   - Or use: `DEEPSEEK_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY`
5) Set start command to: `python main.py`
6) Deploy and your bot runs 24/7 for free!

Check their guide: https://wispbyte.com/kb or join their Discord at https://wispbyte.com/discord

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
