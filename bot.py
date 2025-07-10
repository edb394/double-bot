import discord
from discord.ext import commands, tasks
import asyncio
import datetime
import pytz
from gtts import gTTS
import os
import re

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

# In-memory schedule: {day: [(hour, minute, voice_channel_id)]}
schedule = {}

# TTS engine
def speak_text(text):
    tts = gTTS(text)
    tts.save("output.mp3")

# Utility to normalize voice channel names
def normalize(text):
    return re.sub(r"\s+", " ", text.strip().lower())

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
    session_checker.start()

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
            return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id

        try:
            reply = await bot.wait_for("message", timeout=30.0, check=check)
            user_input = normalize(reply.content)
            print(f"[DEBUG] User input normalized: '{user_input}'")
            all_channels = [normalize(vc.name) for vc in ctx.guild.voice_channels]
            print(f"[DEBUG] Server channels: {all_channels}")
            voice_channel = next(
                (vc for vc in ctx.guild.voice_channels if normalize(vc.name) == user_input),
                None
            )
            if not voice_channel:
                await ctx.send("❌ Could not find that voice channel.")
                return
        except asyncio.TimeoutError:
            await ctx.send("❌ Timed out waiting for channel name.")
            return


    schedule.setdefault(day, []).append((hour, minute, voice_channel.id))
    await ctx.send(f"✅ Scheduled for {day} at {hour:02d}:{minute:02d} in {voice_channel.name}.")

@bot.command()
async def show_schedule(ctx):
    if not schedule:
        await ctx.send("📭 No sessions scheduled.")
        return
    msg = "🗓️ Scheduled Sessions:\n"
    for day, entries in schedule.items():
        for hour, minute, vc_id in entries:
            channel = discord.utils.get(ctx.guild.voice_channels, id=vc_id)
            channel_name = channel.name if channel else "Unknown Channel"
            msg += f"• {day} {hour:02d}:{minute:02d} in {channel_name}\n"
    await ctx.send(msg)

@bot.command()
async def clear_schedule(ctx):
    schedule.clear()
    await ctx.send("🧹 Cleared all scheduled sessions.")

@bot.command()
async def end(ctx):
    if ctx.voice_client:
        await ctx.voice_client.disconnect()
        await ctx.send("👋 Session ended.")
    else:
        await ctx.send("❌ I'm not in a voice channel.")

@bot.command()
async def debug(ctx):
    await ctx.send(f"🛠 Internal schedule state: `{schedule}`")

# ------------ TASK LOOP ------------
@tasks.loop(minutes=1)
async def session_checker():
    now = datetime.datetime.now(TIMEZONE)
    current_day = now.strftime("%a")
    if current_day not in schedule:
        return
    for hour, minute, vc_id in schedule[current_day]:
        if now.hour == hour and now.minute == minute:
            for guild in bot.guilds:
                voice_channel = discord.utils.get(guild.voice_channels, id=vc_id)
                if voice_channel:
                    try:
                        vc = await voice_channel.connect()
                        speak_text("Hi Evan, let’s get started. What’s your first priority today?")
                        if os.path.exists("output.mp3"):
                            vc.play(discord.FFmpegPCMAudio("output.mp3"))
                        await asyncio.sleep(30)
                        await vc.disconnect()
                    except Exception as e:
                        print(f"[ERROR] Failed to join/play in {voice_channel.name}: {e}")

bot.run(BOT_TOKEN)
