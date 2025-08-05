
import discord
import yt_dlp as youtube_dl
from collections import deque

QUEUE_LIMIT = 10

guild_queues = {}  # {guild_id: deque([...])}
guild_playing = {} # {guild_id: bool}

def register_music_commands(bot):
    # 현재 재생 중인 곡 정보를 저장
    current_song = {}

    @bot.slash_command(guild_id=[1345392235264348170, 540157160961867796, 326024303948857356], description="Show info about the currently playing song.")
    async def nowplaying(ctx):
        guild_id = ctx.guild.id
        song = current_song.get(guild_id)
        if song:
            await ctx.respond(f'Now playing: {song["title"]}\nURL: {song["url"]}')
        else:
            await ctx.respond('No song is currently playing.')
    @bot.slash_command(guild_id=[1345392235264348170, 540157160961867796, 326024303948857356], description="Disconnect the bot from the voice channel.")
    async def leave(ctx):
        voice_client = ctx.voice_client
        if voice_client:
            await voice_client.disconnect()
            guild_id = ctx.guild.id
            if guild_id in guild_playing:
                guild_playing[guild_id] = False
            if guild_id in guild_queues:
                guild_queues[guild_id].clear()
            await ctx.respond("Bot has left the voice channel and cleared the queue.")
        else:
            await ctx.respond("Bot is not connected to any voice channel.")

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
            # 현재 곡 정보 저장
            current_song[guild_id] = {'title': next_song['title'], 'url': next_song['url']}
            def after_playing(error):
                coro = play_next(next_song['ctx'])
                fut = discord.utils.get_event_loop().create_task(coro)
            source = discord.FFmpegPCMAudio(next_song['url'])
            voice_client.play(source, after=after_playing)
            # 곡 정보와 URL을 함께 출력
            coro = next_song['ctx'].respond(f'Now playing: {next_song["title"]}\nURL: {next_song["url"]}')
            fut = discord.utils.get_event_loop().create_task(coro)
        else:
            guild_playing[guild_id] = False
            current_song[guild_id] = None
    # play_next를 외부에서 쓸 수 있게 등록
    bot.play_next = play_next

def register_music_events(bot):
    @bot.event
    async def on_voice_state_update(member, before, after):
        if member.guild.voice_client and member.guild.voice_client.channel:
            channel = member.guild.voice_client.channel
            human_members = [m for m in channel.members if not m.bot]
            if len(human_members) == 0:
                await member.guild.voice_client.disconnect()
                guild_id = member.guild.id
                if guild_id in guild_playing:
                    guild_playing[guild_id] = False
                if guild_id in guild_queues:
                    guild_queues[guild_id].clear()
