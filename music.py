
import discord
import asyncio
import yt_dlp as youtube_dl
from collections import deque

QUEUE_LIMIT = 10

guild_queues = {}  # {guild_id: deque([...])}
guild_playing = {} # {guild_id: bool}

def register_music_commands(bot):
    import random

    @bot.slash_command(guild_id=[1345392235264348170, 540157160961867796, 326024303948857356], description="Repeat the current song.")
    async def repeat(ctx):
        guild_id = ctx.guild.id
        voice_client = ctx.voice_client
        current = None
        # 현재 곡 정보 가져오기
        if hasattr(bot, 'play_next') and hasattr(bot.play_next, '__closure__'):
            # current_song dict 접근
            for cell in bot.play_next.__closure__:
                if isinstance(cell.cell_contents, dict) and 'title' in cell.cell_contents.get(guild_id, {}):
                    current = cell.cell_contents.get(guild_id)
                    break
        # fallback: nowplaying 명령어에서 사용하는 current_song dict
        if not current:
            current = globals().get('current_song', {}).get(guild_id)
        if current:
            guild_queues[guild_id].appendleft({'url': current['url'], 'title': current['title'], 'ctx': ctx})
            await ctx.respond(f'Repeated: {current["title"]}')
        else:
            await ctx.respond('No song is currently playing.')

    @bot.slash_command(guild_id=[1345392235264348170, 540157160961867796, 326024303948857356], description="Shuffle the music queue.")
    async def shuffle(ctx):
        guild_id = ctx.guild.id
        q = guild_queues.get(guild_id, deque())
        if len(q) < 2:
            await ctx.respond('Not enough songs in queue to shuffle.')
            return
        random.shuffle(q)
        await ctx.respond('Queue shuffled.')
    @bot.slash_command(guild_id=[1345392235264348170, 540157160961867796, 326024303948857356], description="Skip the current song.")
    async def skip(ctx):
        voice_client = ctx.voice_client
        if voice_client and voice_client.is_playing():
            voice_client.stop()
            await ctx.respond('Skipped current song.')
            # 다음 곡 자동 재생
            await bot.play_next(ctx)
        else:
            await ctx.respond('Nothing is playing to skip.')
    @bot.slash_command(guild_id=[1345392235264348170, 540157160961867796, 326024303948857356], description="Pause the current song.")
    async def pause(ctx):
        voice_client = ctx.voice_client
        if voice_client and voice_client.is_playing():
            voice_client.pause()
            await ctx.respond('Playback paused.')
        else:
            await ctx.respond('Nothing is playing right now.')

    @bot.slash_command(guild_id=[1345392235264348170, 540157160961867796, 326024303948857356], description="Resume the paused song.")
    async def resume(ctx):
        voice_client = ctx.voice_client
        if voice_client and voice_client.is_paused():
            voice_client.resume()
            await ctx.respond('Playback resumed.')
        else:
            await ctx.respond('Nothing is paused right now.')
    @bot.slash_command(guild_id=[1345392235264348170, 540157160961867796, 326024303948857356], description="Show the current music queue.")
    async def queue(ctx):
        guild_id = ctx.guild.id
        q = guild_queues.get(guild_id, deque())
        if not q:
            await ctx.respond('Queue is empty.')
        else:
            msg = '\n'.join([f'{i+1}. {item["title"]}' for i, item in enumerate(q)])
            await ctx.respond(f'Current queue:\n{msg}')

    @bot.slash_command(guild_id=[1345392235264348170, 540157160961867796, 326024303948857356], description="Remove a song from the queue by its position.")
    async def remove(ctx, position: int):
        guild_id = ctx.guild.id
        q = guild_queues.get(guild_id, deque())
        if not q:
            await ctx.respond('Queue is empty.')
            return
        if position < 1 or position > len(q):
            await ctx.respond('Invalid position.')
            return
        removed = q[position-1]['title']
        del q[position-1]
        await ctx.respond(f'Removed from queue: {removed}')

    @bot.slash_command(guild_id=[1345392235264348170, 540157160961867796, 326024303948857356], description="Clear the entire music queue.")
    async def clear(ctx):
        guild_id = ctx.guild.id
        q = guild_queues.get(guild_id, deque())
        if not q:
            await ctx.respond('Queue is already empty.')
        else:
            q.clear()
            await ctx.respond('Queue cleared.')
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
        await ctx.defer()
        try:
            if guild_id not in guild_queues:
                guild_queues[guild_id] = deque()
                guild_playing[guild_id] = False
            # queue 길이 제한 체크
            if len(guild_queues[guild_id]) >= QUEUE_LIMIT:
                await ctx.followup.send(f'Queue is full! (최대 {QUEUE_LIMIT}곡까지 가능)')
                return
            if not ctx.voice_client:
                if ctx.author.voice:
                    channel = ctx.author.voice.channel
                    try:
                        await channel.connect()
                    except Exception as e:
                        await ctx.followup.send(f'Failed to connect to voice channel: {e}')
                        return
                else:
                    await ctx.followup.send("You need to be in a voice channel to play music.")
                    return
            ydl_opts = {
                'format': 'bestaudio',
                'quiet': True,
            }
            try:
                with youtube_dl.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    # 오디오가 있는 format만 선택
                    audio_formats = [f for f in info['formats'] if f.get('acodec') != 'none' and f.get('url')]
                    if not audio_formats:
                        await ctx.followup.send('No audio stream found for this video.')
                        return
                    stream_url = audio_formats[0]['url']
                    title = info.get('title', 'Unknown Title')
            except Exception as e:
                await ctx.followup.send(f'Failed to fetch audio: {e}')
                return
            guild_queues[guild_id].append({'url': stream_url, 'title': title, 'ctx': ctx})
            await ctx.followup.send(f'Added to queue: {title}')
            if not guild_playing[guild_id]:
                await play_next(ctx)
        except Exception as e:
            await ctx.followup.send(f'Unexpected error: {e}')

    # 메인 이벤트 루프를 전역 변수로 저장
    main_loop = asyncio.get_event_loop()

    async def play_next(ctx):
        guild_id = ctx.guild.id
        try:
            if guild_queues[guild_id]:
                next_song = guild_queues[guild_id].popleft()
                voice_client = ctx.voice_client
                guild_playing[guild_id] = True
                # 현재 곡 정보 저장
                current_song[guild_id] = {'title': next_song['title'], 'url': next_song['url']}
                def after_playing(error):
                    coro = play_next(next_song['ctx'])
                    asyncio.run_coroutine_threadsafe(coro, main_loop)
                try:
                    source = discord.FFmpegPCMAudio(
                        next_song['url'],
                        before_options='-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5'
                    )
                    voice_client.play(source, after=after_playing)
                except Exception as e:
                    await next_song['ctx'].respond(f'Failed to play audio: {e}')
                    guild_playing[guild_id] = False
                    current_song[guild_id] = None
                    return
                # 곡 정보와 URL을 함께 출력
                coro = next_song['ctx'].respond(f'Now playing: {next_song["title"]}\nURL: {next_song["url"]}')
                asyncio.run_coroutine_threadsafe(coro, main_loop)
            else:
                guild_playing[guild_id] = False
                current_song[guild_id] = None
        except Exception as e:
            await ctx.respond(f'Unexpected error: {e}')

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
