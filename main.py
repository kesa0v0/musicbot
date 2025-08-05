import discord

# 봇 객체 및 기본 이벤트만 담당
from dotenv import load_dotenv
import os

load_dotenv()
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')

bot = discord.Bot()

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')

# 음악 기능 import
from music import register_music_commands, register_music_events
register_music_commands(bot)
register_music_events(bot)

bot.run(DISCORD_TOKEN)
