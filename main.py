from __future__ import annotations

import asyncio
import html
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import aiohttp
import discord
from discord import app_commands
from dotenv import load_dotenv
from langdetect import LangDetectException, detect

BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config.json"
SETTINGS_PATH = BASE_DIR / "data" / "guild_settings.json"
USER_SETTINGS_PATH = BASE_DIR / "data" / "user_settings.json"

DEFAULT_CONFIG: Dict[str, Any] = {
    "default_provider": "deepseek",
    "default_mode": "auto",
    "default_source_language": "auto",
    "default_target_language": "auto-bidir",
    "bidir_languages": ["en", "zh"],
    "fallback_target_language": "en",
    "default_display_mode": "webhook",
}

CJK_RE = re.compile(r"[\u4e00-\u9fff]")

PROVIDERS = ["deepseek", "openai", "google", "gemini"]
MODES = ["auto", "mirror", "command"]
DISPLAY_MODES = ["embed", "text", "webhook"]
LANGUAGE_CHOICES = ["auto", "auto-bidir", "en", "zh"]
RESERVED_LANGUAGE_CHOICES = {"auto", "auto-bidir"}
LANGUAGE_CODE_RE = re.compile(r"^[a-z]{2,3}(-[a-z]{2})?$")


def load_config() -> Dict[str, Any]:
    if CONFIG_PATH.exists():
        with CONFIG_PATH.open("r", encoding="utf-8") as f:
            user_config = json.load(f)
        merged = {**DEFAULT_CONFIG, **user_config}
        return merged
    return DEFAULT_CONFIG.copy()


@dataclass
class GuildSettings:
    provider: str
    mode: str
    source_language: str
    target_language: str
    display_mode: str
    auto_translate_channels: List[int]
    mirror_pairs: List[Dict[str, int]]


@dataclass
class UserSettings:
    source_language: Optional[str]
    target_language: Optional[str]


class SettingsManager:
    def __init__(self, config: Dict[str, Any]) -> None:
        self._config = config
        self._lock = asyncio.Lock()
        self._settings: Dict[str, Dict[str, Any]] = {}
        self._user_settings: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self._load()

    def _default_settings(self) -> Dict[str, Any]:
        return {
            "provider": self._config["default_provider"],
            "mode": self._config["default_mode"],
            "source_language": self._config["default_source_language"],
            "target_language": self._config["default_target_language"],
            "display_mode": self._config["default_display_mode"],
            "auto_translate_channels": [],
            "mirror_pairs": [],
        }

    def _load(self) -> None:
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        if SETTINGS_PATH.exists():
            with SETTINGS_PATH.open("r", encoding="utf-8") as f:
                self._settings = json.load(f)
        else:
            self._settings = {}
            self._save()

        if USER_SETTINGS_PATH.exists():
            with USER_SETTINGS_PATH.open("r", encoding="utf-8") as f:
                self._user_settings = json.load(f)
        else:
            self._user_settings = {}
            self._save_user_settings()

    def _save(self) -> None:
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with SETTINGS_PATH.open("w", encoding="utf-8") as f:
            json.dump(self._settings, f, indent=2, ensure_ascii=False)

    def _save_user_settings(self) -> None:
        USER_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with USER_SETTINGS_PATH.open("w", encoding="utf-8") as f:
            json.dump(self._user_settings, f, indent=2, ensure_ascii=False)

    async def get_settings(self, guild_id: int) -> GuildSettings:
        async with self._lock:
            key = str(guild_id)
            if key not in self._settings:
                self._settings[key] = self._default_settings()
                self._save()
            data = {**self._default_settings(), **self._settings[key]}
            return GuildSettings(**data)

    async def update_settings(self, guild_id: int, updates: Dict[str, Any]) -> None:
        async with self._lock:
            key = str(guild_id)
            if key not in self._settings:
                self._settings[key] = self._default_settings()
            self._settings[key].update(updates)
            self._save()

    async def get_user_settings(self, guild_id: int, user_id: int) -> UserSettings:
        async with self._lock:
            gid = str(guild_id)
            uid = str(user_id)
            guild_users = self._user_settings.get(gid, {})
            data = guild_users.get(uid, {})
            return UserSettings(
                source_language=data.get("source_language"),
                target_language=data.get("target_language"),
            )

    async def update_user_settings(self, guild_id: int, user_id: int, updates: Dict[str, Any]) -> None:
        async with self._lock:
            gid = str(guild_id)
            uid = str(user_id)
            if gid not in self._user_settings:
                self._user_settings[gid] = {}
            if uid not in self._user_settings[gid]:
                self._user_settings[gid][uid] = {}
            self._user_settings[gid][uid].update(updates)
            self._save_user_settings()

    async def clear_user_settings(self, guild_id: int, user_id: int) -> None:
        async with self._lock:
            gid = str(guild_id)
            uid = str(user_id)
            if gid in self._user_settings and uid in self._user_settings[gid]:
                self._user_settings[gid].pop(uid, None)
                self._save_user_settings()

    async def add_mirror_pair(self, guild_id: int, source: int, target: int) -> None:
        async with self._lock:
            key = str(guild_id)
            if key not in self._settings:
                self._settings[key] = self._default_settings()
            pairs = self._settings[key].setdefault("mirror_pairs", [])
            if not any(p["source_channel_id"] == source and p["target_channel_id"] == target for p in pairs):
                pairs.append({"source_channel_id": source, "target_channel_id": target})
            self._save()

    async def remove_mirror_pair(self, guild_id: int, source: int, target: int) -> None:
        async with self._lock:
            key = str(guild_id)
            if key not in self._settings:
                return
            pairs = self._settings[key].get("mirror_pairs", [])
            self._settings[key]["mirror_pairs"] = [
                p for p in pairs if not (p["source_channel_id"] == source and p["target_channel_id"] == target)
            ]
            self._save()

    async def set_auto_channel(self, guild_id: int, channel_id: int, enabled: bool) -> None:
        async with self._lock:
            key = str(guild_id)
            if key not in self._settings:
                self._settings[key] = self._default_settings()
            channels = self._settings[key].setdefault("auto_translate_channels", [])
            if enabled:
                if channel_id not in channels:
                    channels.append(channel_id)
            else:
                if channel_id in channels:
                    channels.remove(channel_id)
            self._save()


class Translator:
    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session

    async def translate(self, provider: str, text: str, source: str, target: str) -> str:
        if provider == "deepseek":
            return await self._translate_openai_compatible(
                base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
                api_key=os.getenv("DEEPSEEK_API_KEY"),
                model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
                text=text,
                source=source,
                target=target,
            )
        if provider == "openai":
            return await self._translate_openai_compatible(
                base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
                api_key=os.getenv("OPENAI_API_KEY"),
                model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                text=text,
                source=source,
                target=target,
            )
        if provider == "google":
            return await self._translate_google(text=text, source=source, target=target)
        if provider == "gemini":
            return await self._translate_gemini(text=text, source=source, target=target)
        raise ValueError(f"Unsupported provider: {provider}")

    async def _translate_openai_compatible(
        self,
        base_url: str,
        api_key: Optional[str],
        model: str,
        text: str,
        source: str,
        target: str,
    ) -> str:
        if not api_key:
            raise RuntimeError("Missing API key for selected provider.")
        url = f"{base_url.rstrip('/')}/chat/completions"
        system_prompt = "You are a translation engine. Return only the translated text, no extra commentary."
        user_prompt = f"Translate from {source} to {target}. Text:\n{text}"
        payload = {
            "model": model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        async with self._session.post(url, json=payload, headers=headers, timeout=30) as resp:
            data = await resp.json()
            if resp.status >= 400:
                raise RuntimeError(f"Translation API error: {data}")
            return data["choices"][0]["message"]["content"].strip()

    async def _translate_google(self, text: str, source: str, target: str) -> str:
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise RuntimeError("Missing GOOGLE_API_KEY for Google provider.")
        url = f"https://translation.googleapis.com/language/translate/v2?key={api_key}"
        payload: Dict[str, Any] = {"q": text, "target": target, "format": "text"}
        if source != "auto":
            payload["source"] = source
        async with self._session.post(url, json=payload, timeout=30) as resp:
            data = await resp.json()
            if resp.status >= 400:
                raise RuntimeError(f"Translation API error: {data}")
            translated = data["data"]["translations"][0]["translatedText"]
            return html.unescape(translated)

    async def _translate_gemini(self, text: str, source: str, target: str) -> str:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("Missing GEMINI_API_KEY for Gemini provider.")
        model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        model_path = model if model.startswith("models/") else f"models/{model}"
        url = (
            "https://generativelanguage.googleapis.com/v1/"
            f"{model_path}:generateContent?key={api_key}"
        )
        prompt = (
            "You are a translation engine. Return only the translated text, no extra commentary.\n"
            f"Translate from {source} to {target}. Text:\n{text}"
        )
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt}],
                }
            ],
            "generationConfig": {"temperature": 0},
        }
        async with self._session.post(url, json=payload, timeout=30) as resp:
            data = await resp.json()
            if resp.status >= 400:
                raise RuntimeError(f"Translation API error: {data}")
            try:
                return data["candidates"][0]["content"]["parts"][0]["text"].strip()
            except (KeyError, IndexError, TypeError):
                raise RuntimeError(f"Unexpected Gemini response: {data}")


class TranslateBot(discord.Client):
    def __init__(self, settings_manager: SettingsManager, config: Dict[str, Any]) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.settings_manager = settings_manager
        self.config = config
        self.session: Optional[aiohttp.ClientSession] = None
        self.translator: Optional[Translator] = None

    async def setup_hook(self) -> None:
        self.session = aiohttp.ClientSession()
        self.translator = Translator(self.session)
        await self.tree.sync()

    async def close(self) -> None:
        if self.session:
            await self.session.close()
        await super().close()


load_dotenv(dotenv_path=BASE_DIR / ".env")
load_dotenv(dotenv_path=BASE_DIR / ".env.gemini", override=False)
config = load_config()
settings_manager = SettingsManager(config)

bot = TranslateBot(settings_manager, config)


def is_admin(interaction: discord.Interaction) -> bool:
    if not interaction.guild or not interaction.user:
        return False
    perms = interaction.user.guild_permissions
    return perms.manage_guild or perms.administrator


def detect_bidir_language(text: str, languages: List[str]) -> Tuple[str, str]:
    if CJK_RE.search(text):
        return "zh", "en"
    return "en", "zh"


def detect_language(text: str) -> Optional[str]:
    try:
        return detect(text).lower()
    except LangDetectException:
        return None


def is_valid_language(code: str) -> bool:
    code = code.lower()
    if code in RESERVED_LANGUAGE_CHOICES:
        return True
    return bool(LANGUAGE_CODE_RE.match(code))


def resolve_languages(settings: GuildSettings, user_settings: UserSettings, text: str) -> Tuple[str, str]:
    source = (user_settings.source_language or settings.source_language).lower()
    target = (user_settings.target_language or settings.target_language).lower()

    detected = None
    if source == "auto" or target == "auto":
        detected = detect_language(text)

    if target == "auto-bidir":
        source, target = detect_bidir_language(text, config["bidir_languages"])
        if detected:
            source = detected
    elif target == "auto":
        if detected:
            source = detected if source == "auto" else source
        fallback = config.get("fallback_target_language", "en").lower()
        target = fallback
    else:
        if source == "auto" and detected:
            source = detected

    return source, target


def build_embed(
    original_text: str,
    translated_text: str,
    source: str,
    target: str,
    author: discord.User | discord.Member,
) -> discord.Embed:
    embed = discord.Embed(
        title=f"Translation ({source} → {target})",
        color=discord.Color.blurple(),
    )
    embed.add_field(name=f"Original ({source})", value=original_text, inline=False)
    embed.add_field(name=f"Translation ({target})", value=translated_text, inline=False)
    embed.set_author(name=f"{author.display_name} APP", icon_url=author.display_avatar.url)
    return embed


async def send_translation(
    channel: discord.abc.Messageable,
    original_text: str,
    translated_text: str,
    source: str,
    target: str,
    author: discord.User | discord.Member,
    display_mode: str,
) -> None:
    # Webhook mode (looks like user posted it)
    if display_mode == "webhook" and isinstance(channel, discord.TextChannel):
        try:
            webhook = None
            for wh in await channel.webhooks():
                if wh.name == "translate-bot":
                    webhook = wh
                    break
            if not webhook:
                webhook = await channel.create_webhook(name="translate-bot")
            
            if display_mode == "webhook":
                embed = build_embed(original_text, translated_text, source, target, author)
                await webhook.send(embed=embed, username=author.display_name, avatar_url=author.display_avatar.url)
                return
        except discord.Forbidden:
            pass
    
    # Embed mode (box)
    if display_mode == "embed":
        embed = build_embed(original_text, translated_text, source, target, author)
        await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
    # Plain text mode
    elif display_mode == "text":
        content = f"**Original ({source}):** {original_text}\n**Translation ({target}):** {translated_text}"
        await channel.send(content, allowed_mentions=discord.AllowedMentions.none())


@bot.event
async def on_message(message: discord.Message) -> None:
    if message.author.bot or not message.guild:
        return

    settings = await settings_manager.get_settings(message.guild.id)
    user_settings = await settings_manager.get_user_settings(message.guild.id, message.author.id)
    if settings.mode == "auto":
        if settings.auto_translate_channels and message.channel.id not in settings.auto_translate_channels:
            return
        source, target = resolve_languages(settings, user_settings, message.content)
        if not bot.translator:
            return
        try:
            translated = await bot.translator.translate(settings.provider, message.content, source, target)
        except Exception:
            return
        await send_translation(
            channel=message.channel,
            original_text=message.content,
            translated_text=translated,
            source=source,
            target=target,
            author=message.author,
            display_mode=settings.display_mode,
        )
        try:
            await message.delete()
        except discord.Forbidden:
            pass
    elif settings.mode == "mirror":
        if not bot.translator:
            return
        for pair in settings.mirror_pairs:
            if message.channel.id == pair["source_channel_id"]:
                target_channel = bot.get_channel(pair["target_channel_id"])
                if not target_channel:
                    continue
                source, target = resolve_languages(settings, user_settings, message.content)
                try:
                    translated = await bot.translator.translate(settings.provider, message.content, source, target)
                except Exception:
                    continue
                await send_translation(
                    channel=target_channel,
                    original_text=message.content,
                    translated_text=translated,
                    source=source,
                    target=target,
                    author=message.author,
                    display_mode=settings.display_mode,
                )


@bot.tree.command(name="translate", description="Translate a piece of text")
@app_commands.describe(text="Text to translate", target="Target language", source="Source language")
async def translate_command(
    interaction: discord.Interaction,
    text: str,
    target: Optional[str] = None,
    source: Optional[str] = None,
) -> None:
    if not interaction.guild:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return
    settings = await settings_manager.get_settings(interaction.guild.id)
    user_settings = await settings_manager.get_user_settings(interaction.guild.id, interaction.user.id)
    use_source = (source or user_settings.source_language or settings.source_language).lower()
    use_target = (target or user_settings.target_language or settings.target_language).lower()
    temp_settings = GuildSettings(
        provider=settings.provider,
        mode=settings.mode,
        source_language=use_source,
        target_language=use_target,
        use_embeds=settings.use_embeds,
        auto_translate_channels=settings.auto_translate_channels,
        mirror_pairs=settings.mirror_pairs,
    )
    temp_user_settings = UserSettings(source_language=use_source, target_language=use_target)
    source_lang, target_lang = resolve_languages(temp_settings, temp_user_settings, text)
    if not bot.translator:
        await interaction.response.send_message("Translator not ready.", ephemeral=True)
        return
    try:
        translated = await bot.translator.translate(settings.provider, text, source_lang, target_lang)
    except Exception as exc:
        await interaction.response.send_message(f"Translation failed: {exc}", ephemeral=True)
        return
    if settings.use_embeds:
        embed = build_embed(text, translated, source_lang, target_lang, interaction.user)
        await interaction.response.send_message(embed=embed)
    else:
        await interaction.response.send_message(f"**Original ({source_lang}):** {text}\n**Translation ({target_lang}):** {translated}")


@bot.tree.command(name="set_mode", description="Set translation mode for this server")
@app_commands.describe(mode="auto, mirror, or command")
async def set_mode(interaction: discord.Interaction, mode: str) -> None:
    if not interaction.guild:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return
    if not is_admin(interaction):
        await interaction.response.send_message("You need Manage Server to do that.", ephemeral=True)
        return
    if mode not in MODES:
        await interaction.response.send_message(f"Invalid mode. Choose: {', '.join(MODES)}", ephemeral=True)
        return
    await settings_manager.update_settings(interaction.guild.id, {"mode": mode})
    await interaction.response.send_message(f"Mode set to {mode}.", ephemeral=True)


@bot.tree.command(name="set_provider", description="Set translation provider")
@app_commands.describe(provider="deepseek, openai, google, or gemini")
async def set_provider(interaction: discord.Interaction, provider: str) -> None:
    if not interaction.guild:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return
    if not is_admin(interaction):
        await interaction.response.send_message("You need Manage Server to do that.", ephemeral=True)
        return
    if provider not in PROVIDERS:
        await interaction.response.send_message(f"Invalid provider. Choose: {', '.join(PROVIDERS)}", ephemeral=True)
        return
    await settings_manager.update_settings(interaction.guild.id, {"provider": provider})
    await interaction.response.send_message(f"Provider set to {provider}.", ephemeral=True)


@bot.tree.command(name="set_languages", description="Set source and target languages")
@app_commands.describe(source="auto or language code", target="auto/auto-bidir or language code")
async def set_languages(interaction: discord.Interaction, source: str, target: str) -> None:
    if not interaction.guild:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return
    if not is_admin(interaction):
        await interaction.response.send_message("You need Manage Server to do that.", ephemeral=True)
        return
    source = source.lower()
    target = target.lower()
    if not is_valid_language(source) or not is_valid_language(target):
        await interaction.response.send_message(
            "Invalid languages. Use auto, auto-bidir, or a language code like en, zh, ja.",
            ephemeral=True,
        )
        return
    await settings_manager.update_settings(
        interaction.guild.id,
        {"source_language": source, "target_language": target},
    )
    await interaction.response.send_message(
        f"Languages set to source={source}, target={target}.", ephemeral=True
    )


@bot.tree.command(name="set_user_languages", description="Set your personal source/target languages")
@app_commands.describe(source="auto or language code", target="auto/auto-bidir or language code")
async def set_user_languages(interaction: discord.Interaction, source: str, target: str) -> None:
    if not interaction.guild:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return
    source = source.lower()
    target = target.lower()
    if not is_valid_language(source) or not is_valid_language(target):
        await interaction.response.send_message(
            "Invalid languages. Use auto, auto-bidir, or a language code like en, zh, ja.",
            ephemeral=True,
        )
        return
    await settings_manager.update_user_settings(
        interaction.guild.id,
        interaction.user.id,
        {"source_language": source, "target_language": target},
    )
    await interaction.response.send_message(
        f"Personal languages set to source={source}, target={target}.",
        ephemeral=True,
    )


@bot.tree.command(name="clear_user_languages", description="Clear your personal language overrides")
async def clear_user_languages(interaction: discord.Interaction) -> None:
    if not interaction.guild:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return
    await settings_manager.clear_user_settings(interaction.guild.id, interaction.user.id)
    await interaction.response.send_message("Personal language overrides cleared.", ephemeral=True)


@bot.tree.command(name="my_languages", description="Show your personal language settings")
async def my_languages(interaction: discord.Interaction) -> None:
    if not interaction.guild:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return
    user_settings = await settings_manager.get_user_settings(interaction.guild.id, interaction.user.id)
    source = user_settings.source_language or "(inherit server)"
    target = user_settings.target_language or "(inherit server)"
    await interaction.response.send_message(
        f"Personal languages: source={source}, target={target}",
        ephemeral=True,
    )


@bot.tree.command(name="set_auto_channel", description="Enable/disable auto-translate for this channel")
@app_commands.describe(enabled="Enable or disable auto-translate in this channel")
async def set_auto_channel(interaction: discord.Interaction, enabled: bool) -> None:
    if not interaction.guild or not interaction.channel:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return
    if not is_admin(interaction):
        await interaction.response.send_message("You need Manage Server to do that.", ephemeral=True)
        return
    await settings_manager.set_auto_channel(interaction.guild.id, interaction.channel.id, enabled)
    await interaction.response.send_message(
        f"Auto-translate {'enabled' if enabled else 'disabled'} for this channel.",
        ephemeral=True,
    )


@bot.tree.command(name="set_mirror", description="Mirror a source channel to a target channel")
@app_commands.describe(source_channel="Channel to listen to", target_channel="Channel to send translations to")
async def set_mirror(
    interaction: discord.Interaction,
    source_channel: discord.TextChannel,
    target_channel: discord.TextChannel,
) -> None:
    if not interaction.guild:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return
    if not is_admin(interaction):
        await interaction.response.send_message("You need Manage Server to do that.", ephemeral=True)
        return
    await settings_manager.add_mirror_pair(interaction.guild.id, source_channel.id, target_channel.id)
    await interaction.response.send_message(
        f"Mirror added: {source_channel.mention} → {target_channel.mention}",
        ephemeral=True,
    )


@bot.tree.command(name="remove_mirror", description="Remove a mirrored channel pair")
@app_commands.describe(source_channel="Channel to stop listening to", target_channel="Channel to stop sending to")
async def remove_mirror(
    interaction: discord.Interaction,
    source_channel: discord.TextChannel,
    target_channel: discord.TextChannel,
) -> None:
    if not interaction.guild:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return
    if not is_admin(interaction):
        await interaction.response.send_message("You need Manage Server to do that.", ephemeral=True)
        return
    await settings_manager.remove_mirror_pair(interaction.guild.id, source_channel.id, target_channel.id)
    await interaction.response.send_message(
        f"Mirror removed: {source_channel.mention} → {target_channel.mention}",
        ephemeral=True,
    )


@bot.tree.command(name="set_display_mode", description="Set display mode: embed, text, or webhook")
@app_commands.describe(mode="embed (box), text (plain), or webhook (user-like)")
async def set_display_mode(interaction: discord.Interaction, mode: str) -> None:
    if not interaction.guild:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return
    if not is_admin(interaction):
        await interaction.response.send_message("You need Manage Server to do that.", ephemeral=True)
        return
    mode = mode.lower()
    if mode not in DISPLAY_MODES:
        await interaction.response.send_message(f"Invalid display mode. Choose: {', '.join(DISPLAY_MODES)}", ephemeral=True)
        return
    await settings_manager.update_settings(interaction.guild.id, {"display_mode": mode})
    await interaction.response.send_message(f"Display mode set to {mode}.", ephemeral=True)


@bot.tree.command(name="set_embeds", description="Enable/disable embed output")
@app_commands.describe(enabled="Use embeds for translations")
async def set_embeds(interaction: discord.Interaction, enabled: bool) -> None:
    if not interaction.guild:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return
    if not is_admin(interaction):
        await interaction.response.send_message("You need Manage Server to do that.", ephemeral=True)
        return
    await settings_manager.update_settings(interaction.guild.id, {"use_embeds": enabled})
    await interaction.response.send_message(
        f"Embeds {'enabled' if enabled else 'disabled'}.",
        ephemeral=True,
    )


@bot.tree.command(name="status", description="Show current translation settings")
async def status(interaction: discord.Interaction) -> None:
    if not interaction.guild:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return
    settings = await settings_manager.get_settings(interaction.guild.id)
    user_settings = await settings_manager.get_user_settings(interaction.guild.id, interaction.user.id)
    embed = discord.Embed(title="Translation Settings", color=discord.Color.green())
    embed.add_field(name="Provider", value=settings.provider, inline=True)
    embed.add_field(name="Mode", value=settings.mode, inline=True)
    embed.add_field(name="Display mode", value=settings.display_mode, inline=True)
    embed.add_field(name="Languages", value=f"{settings.source_language} → {settings.target_language}", inline=False)
    embed.add_field(
        name="Your overrides",
        value=f"{user_settings.source_language or '(inherit)'} → {user_settings.target_language or '(inherit)'}",
        inline=False,
    )
    embed.add_field(name="Embeds", value=str(settings.use_embeds), inline=True)
    if settings.auto_translate_channels:
        channels = " ".join(f"<#{cid}>" for cid in settings.auto_translate_channels)
    else:
        channels = "All channels"
    embed.add_field(name="Auto-translate channels", value=channels, inline=False)
    if settings.mirror_pairs:
        pairs = "\n".join(f"<#{p['source_channel_id']}> → <#{p['target_channel_id']}>" for p in settings.mirror_pairs)
    else:
        pairs = "None"
    embed.add_field(name="Mirror pairs", value=pairs, inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)


if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("Missing DISCORD_TOKEN in environment.")
    bot.run(token)
