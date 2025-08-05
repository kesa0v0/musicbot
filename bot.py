import os
import discord
from discord.ext import commands
from dotenv import load_dotenv

# .env 파일에서 환경 변수를 로드합니다.
load_dotenv()
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')

# 봇의 접두사와 인텐트를 설정합니다.
intents = discord.Intents.default()
intents.message_content = True # 메시지 내용을 읽기 위한 인텐트 활성화
bot = commands.Bot(command_prefix='/', intents=intents)

@bot.event
async def on_ready():
    """봇이 준비되었을 때 실행되는 이벤트입니다."""
    print(f'{bot.user.name}이(가) 성공적으로 로그인했습니다! (ID: {bot.user.id})')
    print('------')

@bot.command(name='ping')
async def ping(ctx):
    """봇의 지연 시간을 확인하는 간단한 테스트 명령어입니다."""
    await ctx.send(f'Pong! {round(bot.latency * 1000)}ms')

# 봇을 실행합니다.
if __name__ == "__main__":
    if DISCORD_TOKEN:
        bot.run(DISCORD_TOKEN)
    else:
        print("오류: DISCORD_TOKEN이 .env 파일에 설정되지 않았습니다.")
