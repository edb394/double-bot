import discord
from discord.ext import commands, tasks
import asyncio
import datetime
import pytz
from gtts import gTTS
import os
import re
import time
import json

print("[BOOT] Starting bot process...")

# ------------ CONFIG ------------
BOT_TOKEN = os.environ["BOT_TOKEN"]
TIMEZONE = pytz.timezone("US/Central")

# ------------ BOT SETUP ------------
intents = discord.Intents.default()
intents.messages = True
intents.guilds = True
intents.voice_states = True
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ------------ STORAGE ------------
SCHEDULE_FILE = "schedule.json"
def load_schedule():
    if os.path.exists(SCHEDULE_FILE):
        with open(SCHEDULE_FILE, "r") as f:
            return json.load(f)
    return {}

def save_schedule():
    with open(SCHEDULE_FILE, "w") as f:
        json.dump(schedule_data, f)

schedule_data = load_schedule()  # {guild_id: {day: [(hour, minute, vc_id)]}}
session_triggered = set()

# Pre-generated fallback TTS
DEFAULT_TTS_FILE = "startup.mp3"
def generate_default_audio():
    if not os.path.exists(DEFAULT_TTS_FILE):
        print("[TTS] Generating default startup audio...")
        gTTS("Hi there, I'm still processing my first message, please wait.").save(DEFAULT_TTS_FILE)
        time.sleep(1)

def speak_text(text):
    print("[TTS] Generating audio...")
    tts = gTTS(text)
    tts.save("output.mp3")
    time.sleep(1)
    print("[TTS] Saved to output.mp3")

# ------------ EVENTS ------------
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user.name}")
    for guild in bot.guilds:
        for channel in guild.text_channels:
            if channel.permissions_for(guild.me).send_messages:
                await channel.send(
                    "👋 Hi! I’m your productivity session bot.\n"
                    "Use `!schedule <day> <HH:MM>` to book a session with me.\n"
                    "Commands:\n• `!schedule Mon 10:00`\n• `!show_schedule`\n• `!clear_schedule`\n• `!end`"
                )
                break
    if not session_checker.is_running():
        session_checker.start()
    generate_default_audio()

# ------------ COMMANDS ------------
@bot.command()
async def schedule(ctx, day: str, time: str):
    author = ctx.author
    voice_state = author.voice

    try:
        hour, minute = map(int, time.split(":"))
    except ValueError:
        await ctx.send("❌ Time format should be HH:MM, e.g., 14:30")
        return

    day = day.capitalize()
    if day not in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]:
        await ctx.send("❌ Invalid day. Use Mon/Tue/Wed/etc.")
        return

    if voice_state and voice_state.channel:
        voice_channel = voice_state.channel
    else:
        await ctx.send("You're not in a voice channel. Please type the name of the one I should join.")

        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel

        try:
            reply = await bot.wait_for("message", timeout=30.0, check=check)
            normalized_name = reply.content.strip().lower()
            for vc in ctx.guild.voice_channels:
                if vc.name.strip().lower() == normalized_name:
                    voice_channel = vc
                    break
            else:
                await ctx.send("❌ Could not find that voice channel.")
                return
        except asyncio.TimeoutError:
            await ctx.send("❌ Timed out waiting for channel name.")
            return

    guild_id = str(ctx.guild.id)
    if guild_id not in schedule_data:
        schedule_data[guild_id] = {}
    schedule_data[guild_id].setdefault(day, []).append((hour, minute, voice_channel.id))
    save_schedule()
    await ctx.send(f"✅ Scheduled for {day} at {hour:02d}:{minute:02d} in {voice_channel.name}.")

@bot.command()
async def show_schedule(ctx):
    guild_id = str(ctx.guild.id)
    if guild_id not in schedule_data or not schedule_data[guild_id]:
        await ctx.send("📜 No sessions scheduled.")
        return
    msg = "🗓️ Scheduled Sessions:\n"
    for day, entries in schedule_data[guild_id].items():
        for hour, minute, vc_id in entries:
            channel_name = discord.utils.get(ctx.guild.voice_channels, id=vc_id).name
            msg += f"• {day} {hour:02d}:{minute:02d} in {channel_name}\n"
    await ctx.send(msg)

@bot.command()
async def clear_schedule(ctx):
    guild_id = str(ctx.guild.id)
    schedule_data[guild_id] = {}
    save_schedule()
    session_triggered.clear()
    await ctx.send("🪩 Cleared all scheduled sessions.")

@bot.command()
async def end(ctx):
    if ctx.voice_client:
        await ctx.voice_client.disconnect()
        await ctx.send("👋 Session ended.")
    else:
        await ctx.send("❌ I'm not in a voice channel.")

# ------------ TASK LOOP ------------
@tasks.loop(seconds=10)
async def session_checker():
    now = datetime.datetime.now(TIMEZONE)
    current_day = now.strftime("%a")
    current_time_key = f"{now.strftime('%a')}-{now.hour:02d}:{now.minute:02d}"
    print(f"[CHECKER] Now: {current_day} {now.strftime('%H:%M')} | Looking for sessions...")

    for guild in bot.guilds:
        guild_id = str(guild.id)
        if guild_id not in schedule_data:
            continue
        if (guild_id, current_time_key) in session_triggered:
            continue

        for hour, minute, vc_id in schedule_data[guild_id].get(current_day, []):
            if now.hour == hour and now.minute == minute:
                session_triggered.add((guild_id, current_time_key))
                print(f"[CHECKER] Found match for {current_day} at {hour:02d}:{minute:02d} in VC ID {vc_id}")
                voice_channel = discord.utils.get(guild.voice_channels, id=vc_id)
                if voice_channel:
                    try:
                        print(f"[VOICE] Attempting to join {voice_channel.name}")

                        if bot.voice_clients:
                            await bot.voice_clients[0].disconnect()

                        vc = await voice_channel.connect()

                        retries = 0
                        while not vc.is_connected():
                            await asyncio.sleep(0.5)
                            retries += 1
                            if retries > 10:
                                print("[ERROR] Voice connection failed to stabilize.")
                                return

                        if os.path.exists(DEFAULT_TTS_FILE):
                            print("[AUDIO] Playing startup message...")
                            audio = discord.FFmpegPCMAudio(DEFAULT_TTS_FILE)
                            vc.play(audio)
                            while vc.is_playing():
                                await asyncio.sleep(1)

                        speak_text("Hi Evan, let’s get started. What’s your first priority today?")
                        if os.path.exists("output.mp3"):
                            print("[AUDIO] Playing session message...")
                            audio = discord.FFmpegPCMAudio("output.mp3")
                            vc.play(audio)
                            while vc.is_playing():
                                await asyncio.sleep(1)
                        else:
                            print("[ERROR] output.mp3 not found.")

                        return

                    except discord.ClientException as ce:
                        print(f"[ERROR] Discord client exception: {ce}")
                        if bot.voice_clients:
                            await bot.voice_clients[0].disconnect()
                        return
                    except Exception as e:
                        print(f"[ERROR] Failed to join/play in {voice_channel.name}: {e}")
                        continue

bot.run(BOT_TOKEN)
