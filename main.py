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

# Cogs 로딩: cogs 폴더에 있는 모든 .py 파일을 자동으로 로드합니다.
for filename in os.listdir('./cogs'):
    if filename.endswith('.py'):
        try:
            bot.load_extension(f'cogs.{filename[:-3]}')
            logging.info(f'Successfully loaded cog: {filename}')
        except Exception as e:
            logging.error(f'Failed to load cog: {filename}', exc_info=True)

bot.run(DISCORD_TOKEN)
