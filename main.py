import discord
import logging

# 봇 객체 및 기본 이벤트만 담당
from dotenv import load_dotenv
import os

load_dotenv()
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')

logging.basicConfig(level=logging.DEBUG, format='[%(asctime)s] %(levelname)s: %(message)s')

logging.getLogger('discord').setLevel(logging.WARNING)
logging.getLogger('discord.http').setLevel(logging.WARNING)
logging.getLogger('yt_dlp').setLevel(logging.WARNING)

bot = discord.Bot()

@bot.event
async def on_ready():
    logging.info(f'Logged in as {bot.user}')

from music import MusicCog
bot.add_cog(MusicCog(bot))

bot.run(DISCORD_TOKEN)
