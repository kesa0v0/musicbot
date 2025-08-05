import os

from dotenv import load_dotenv
import discord
import yt_dlp as youtube_dl

from collections import deque


QUEUE_LIMIT = 10

# .env 파일에서 환경 변수를 로드합니다.
load_dotenv()
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')

bot = discord.Bot()

guild_queues = {}  # {guild_id: deque([...])}
guild_playing = {} # {guild_id: bool}




@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')

@bot.event
async def on_voice_state_update(member, before, after):
    # 봇이 음성 채널에 있을 때만 체크
    if member.guild.voice_client and member.guild.voice_client.channel:
        channel = member.guild.voice_client.channel
        # 봇이 있는 채널에 사람이 남아있는지 확인 (봇 제외)
        human_members = [m for m in channel.members if not m.bot]
        if len(human_members) == 0:
            await member.guild.voice_client.disconnect()
            # queue 및 상태 초기화
            guild_id = member.guild.id
            if guild_id in guild_playing:
                guild_playing[guild_id] = False
            if guild_id in guild_queues:
                guild_queues[guild_id].clear()


@bot.slash_command(guild_id=[1345392235264348170, 540157160961867796, 326024303948857356], description="Ping the bot to check if it's online.")
async def ping(ctx):
    await ctx.respond("Pong! delay: {:.2f} ms".format(bot.latency * 1000))

@bot.slash_command(guild_id=[1345392235264348170, 540157160961867796, 326024303948857356], description="Play a song from YouTube.")
async def play(ctx, url: str):

    guild_id = ctx.guild.id
    if guild_id not in guild_queues:
        guild_queues[guild_id] = deque()
        guild_playing[guild_id] = False

    # queue 길이 제한 체크
    if len(guild_queues[guild_id]) >= QUEUE_LIMIT:
        await ctx.respond(f'Queue is full! (최대 {QUEUE_LIMIT}곡까지 가능)')
        return

    if not ctx.voice_client:
        if ctx.author.voice:
            channel = ctx.author.voice.channel
            await channel.connect()
        else:
            await ctx.respond("You need to be in a voice channel to play music.")
            return

    ydl_opts = {
        'format': 'bestaudio/best',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'quiet': True,
    }

    with youtube_dl.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        stream_url = info['formats'][0]['url']
        title = info.get('title', 'Unknown Title')

    guild_queues[guild_id].append({'url': stream_url, 'title': title, 'ctx': ctx})
    await ctx.respond(f'Added to queue: {title}')

    if not guild_playing[guild_id]:
        await play_next(ctx)

async def play_next(ctx):
    guild_id = ctx.guild.id
    if guild_queues[guild_id]:
        next_song = guild_queues[guild_id].popleft()
        voice_client = ctx.voice_client
        guild_playing[guild_id] = True
        def after_playing(error):
            coro = play_next(next_song['ctx'])
            fut = discord.utils.get_event_loop().create_task(coro)
        source = discord.FFmpegPCMAudio(next_song['url'])
        voice_client.play(source, after=after_playing)
        coro = next_song['ctx'].respond(f'Now playing: {next_song['title']}')
        fut = discord.utils.get_event_loop().create_task(coro)
    else:
        guild_playing[guild_id] = False


bot.run(DISCORD_TOKEN)