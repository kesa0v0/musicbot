import os
from dotenv import load_dotenv

from discord.ext import commands
from discord import FFmpegPCMAudio
import yt_dlp as youtube_dl

# .env 파일에서 환경 변수를 로드합니다.
load_dotenv()
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')

bot = commands.Bot()

# @bot.slash_command()
# async def play(ctx, url: str):
#     if not ctx.author.voice:
#         await ctx
#         return

#     channel = ctx.author.voice.channel
#     voice_channel = await channel.connect()

#     ydl_opts = {
#         'format': 'bestaudio/best',
#         'extractaudio': True,
#         'audioquality': 1,
#         'outtmpl': 'downloads/%(id)s.%(ext)s',
#         'restrictfilenames': True,
#         'noplaylist': True,
#         'quiet': True,
#         'logtostderr': False,
#     }
    
#     with youtube_dl.YoutubeDL(ydl_opts) as ydl:
#         info = ydl.extract_info(url, download=False)
#         url2 = info['formats'][0]['url']
#         voice_channel.play(FFmpegPCMAudio(url2))

#     await ctx.send(f"Now playing: {info['title']}")

@bot.slash_command(description="Ping the bot to check if it's online.")
async def ping(ctx):
    await ctx.send("Pong! delay: {:.2f} ms".format(bot.latency * 1000))

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')

bot.run(DISCORD_TOKEN)