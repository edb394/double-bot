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
import subprocess

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
user_requested_end = set()

# Pre-generated fallback TTS
DEFAULT_TTS_FILE = "startup.mp3"
def generate_default_audio():
    if not os.path.exists(DEFAULT_TTS_FILE):
        print("[TTS] Generating default startup audio...")
        gTTS("Hi there, I'm still processing my first message, please wait.").save(DEFAULT_TTS_FILE)
        time.sleep(1)

def reencode_audio(filename):
    subprocess.run([
        "ffmpeg", "-y", "-i", filename,
        "-ar", "48000", "-ac", "2", "-f", "mp3", f"re_{filename}"
    ])
    os.replace(f"re_{filename}", filename)

def speak_text(text):
    print("[TTS] Generating audio...")
    tts = gTTS(text)
    tts.save("output.mp3")
    reencode_audio("output.mp3")
    time.sleep(1)
    print("[TTS] Saved to output.mp3")

def parse_day_time(day_str, time_str=None):
    now = datetime.datetime.now(TIMEZONE)
    if time_str is None:
        time_str = day_str
        base_time = now.replace(second=0, microsecond=0)
        match = re.match(r'^(\d{1,2})(?::(\d{2}))?\s*(a|am|p|pm)?$', time_str.strip(), re.IGNORECASE)
        if not match:
            return None, None, None
        hour = int(match.group(1))
        minute = int(match.group(2)) if match.group(2) else 0
        suffix = match.group(3)
        if suffix:
            if suffix.lower().startswith('p') and hour != 12:
                hour += 12
            elif suffix.lower().startswith('a') and hour == 12:
                hour = 0
        else:
            if now.hour >= 12 and hour < 12:
                hour += 12
        return now.strftime("%a"), hour, minute

    day_str = day_str.strip().capitalize()
    match = re.match(r'^(\d{1,2})(?::(\d{2}))?\s*(a|am|p|pm)?$', time_str.strip(), re.IGNORECASE)
    if not match:
        return None, None, None
    hour = int(match.group(1))
    minute = int(match.group(2)) if match.group(2) else 0
    suffix = match.group(3)
    if suffix:
        if suffix.lower().startswith('p') and hour != 12:
            hour += 12
        elif suffix.lower().startswith('a') and hour == 12:
            hour = 0
    return day_str, hour, minute

# ------------ EVENTS ------------
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user.name}")

    try:
        subprocess.run(["ffmpeg", "-version"], check=True)
        print("[FFMPEG] ffmpeg is installed and available ✅")
    except Exception as e:
        print(f"[FFMPEG] ERROR: {e}")

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
async def schedule(ctx, *args):
    if len(args) == 0:
        await ctx.send("❌ You must provide at least a time or a day and time.")
        return

    if len(args) == 1:
        parsed = parse_day_time(args[0])
    else:
        parsed = parse_day_time(args[0], args[1])

    if parsed is None or parsed[1] is None:
        await ctx.send("❌ Could not parse time. Examples: `8:00am`, `14:00`, `8am`, `Mon 10:00`")
        return

    day, hour, minute = parsed
    author = ctx.author
    voice_state = author.voice

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
    user_requested_end.add(ctx.guild.id)
    if ctx.voice_client:
        await ctx.voice_client.disconnect()
        await ctx.send("👋 Session ended.")
    else:
        await ctx.send("❌ I'm not in a voice channel.")

# ------------ TASK LOOP ------------
@tasks.loop(seconds=5)
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

                        vc = await voice_channel.connect(reconnect=True, timeout=15.0)

                        for i in range(20):
                            if vc.is_connected() and vc.channel is not None:
                                break
                            print(f"[DEBUG] Waiting for voice connection to stabilize... {i}")
                            await asyncio.sleep(0.5)
                        else:
                            print("[ERROR] Voice connection never stabilized after connect().")
                            await vc.disconnect()
                            return

                        if os.path.exists(DEFAULT_TTS_FILE):
                            print("[AUDIO] Playing startup message...")
                            audio = discord.FFmpegPCMAudio(DEFAULT_TTS_FILE, stderr=subprocess.STDOUT)
                            try:
                                while vc.is_playing():
                                    await asyncio.sleep(1)
                                vc.play(audio)
                                print(f"[DEBUG] vc.is_playing: {vc.is_playing()}")
                                while vc.is_playing():
                                    await asyncio.sleep(1)
                            except discord.ClientException as ce:
                                print(f"[ERROR] Failed to play startup audio: {ce}")

                        speak_text("Hi Evan, let’s get started. What’s your first priority today?")
                        if os.path.exists("output.mp3"):
                            print("[AUDIO] Playing session message...")
                            audio = discord.FFmpegPCMAudio("output.mp3", stderr=subprocess.STDOUT)
                            try:
                                while vc.is_playing():
                                    await asyncio.sleep(1)
                                vc.play(audio)
                                print(f"[DEBUG] vc.is_playing: {vc.is_playing()}")
                                while vc.is_playing():
                                    await asyncio.sleep(1)
                            except discord.ClientException as ce:
                                print(f"[ERROR] Failed to play session message: {ce}")
                        else:
                            print("[ERROR] output.mp3 not found.")

                        if int(guild_id) not in user_requested_end:
                            print("[SESSION] Waiting for !end command to disconnect...")
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
