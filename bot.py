import os
from dotenv import load_dotenv
import discord
import yt_dlp as youtube_dl

# .env 파일에서 환경 변수를 로드합니다.
load_dotenv()
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')

bot = discord.Bot()

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')


@bot.slash_command(guild_id=[1345392235264348170, 540157160961867796, 326024303948857356], description="Ping the bot to check if it's online.")
async def ping(ctx):
    await ctx.respond("Pong! delay: {:.2f} ms".format(bot.latency * 1000))


bot.run(DISCORD_TOKEN)