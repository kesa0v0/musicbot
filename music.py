print('=== music.py started ===', flush=True)


import discord
import asyncio
import yt_dlp as youtube_dl
from collections import deque

import random
import functools


current_song = {}   # {guild_id: {title, url}}
main_loop = asyncio.get_event_loop()
QUEUE_LIMIT = 30

guild_queues = {}  # {guild_id: deque([...])}
guild_playing = {} # {guild_id: bool}
autoplay_enabled = {}  # {guild_id: bool}  # 자동재생 on/off

def get_guild_queue(guild_id):
    """해당 길드의 큐를 반환하며, 없으면 초기화합니다."""
    if guild_id not in guild_queues:
        guild_queues[guild_id] = deque()
        guild_playing[guild_id] = False
    return guild_queues[guild_id]

def is_queue_empty(guild_id):
    return not guild_queues.get(guild_id)

def clear_guild_queue(guild_id):
    q = guild_queues.get(guild_id)
    if q:
        q.clear()

def remove_from_queue(guild_id, position):
    q = guild_queues.get(guild_id)
    if q and 1 <= position <= len(q):
        removed = q[position-1]['title']
        del q[position-1]
        return removed
    return None

def register_music_commands(bot):
    # === 음악 명령어: 도움말 ===
    @bot.slash_command(guild_id=[1345392235264348170, 540157160961867796, 326024303948857356], description="Show all music commands and usage.")
    async def help(ctx):
        help_text = (
            "**[음악봇 명령어 안내]**\n"
            "/play <url> : 유튜브 곡을 큐에 추가 및 재생\n"
            "/playlist <url> : 유튜브 플레이리스트 전체 추가\n"
            "/repeat : 현재 곡 반복\n"
            "/shuffle : 큐 셔플\n"
            "/skip : 현재 곡 스킵\n"
            "/pause : 곡 일시정지\n"
            "/resume : 곡 재개\n"
            "/queue : 큐 목록 보기\n"
            "/remove <번호> : 큐에서 곡 제거\n"
            "/clear : 큐 전체 비우기\n"
            "/nowplaying : 현재 재생 곡 정보\n"
            "/leave : 음성 채널에서 봇 퇴장\n"
            "/autoplay [on/off] : 자동재생 기능 켜기/끄기\n"
        )
        await ctx.respond(help_text)

    # === 음악 명령어: 자동재생 on/off ===
    @bot.slash_command(guild_id=[1345392235264348170, 540157160961867796, 326024303948857356], description="Toggle autoplay (YouTube 추천곡 자동재생) on/off.")
    async def autoplay(ctx, mode: str):
        guild_id = ctx.guild.id
        mode = mode.lower()
        if mode == "on":
            autoplay_enabled[guild_id] = True
            await ctx.respond("Autoplay가 켜졌습니다. (대기열이 비면 유튜브 추천곡이 자동 재생됩니다)")
        elif mode == "off":
            autoplay_enabled[guild_id] = False
            await ctx.respond("Autoplay가 꺼졌습니다.")
        else:
            await ctx.respond("사용법: /autoplay on 또는 /autoplay off")

    # ...existing code...

    # play_next를 bot에 등록
    bot.play_next = play_next

    # === 음악 명령어: 플레이리스트 추가 ===
    @bot.slash_command(guild_id=[1345392235264348170, 540157160961867796, 326024303948857356], description="Play all videos in a YouTube playlist.")
    async def playlist(ctx, url: str):
        guild_id = ctx.guild.id
        await ctx.defer()
        try:
            print(f"[playlist] Command received: guild={guild_id}, url={url}", flush=True)
            if guild_id not in guild_queues:
                guild_queues[guild_id] = deque()
                guild_playing[guild_id] = False
                print(f"[playlist] Initialized queue and playing state for guild {guild_id}", flush=True)
            if not ctx.voice_client:
                if ctx.author.voice:
                    channel = ctx.author.voice.channel
                    try:
                        print(f"[playlist] Connecting to voice channel: {channel}", flush=True)
                        await channel.connect()
                        print(f"[playlist] Connected to voice channel: {channel}", flush=True)
                    except Exception as e:
                        print(f"[playlist] Failed to connect to voice channel: {e}", flush=True)
                        await ctx.followup.send(f'Failed to connect to voice channel: {e}')
                        return
                else:
                    print(f"[playlist] Author not in voice channel", flush=True)
                    await ctx.followup.send("You need to be in a voice channel to play music.")
                    return
            ydl_opts = {
                'format': 'bestaudio',
                'quiet': False,
                'noplaylist': False,
            }

            async def fetch_info():
                loop = asyncio.get_event_loop()
                print(f"[playlist] Starting yt-dlp extraction for url: {url}", flush=True)
                with youtube_dl.YoutubeDL(ydl_opts) as ydl:
                    info = await loop.run_in_executor(None, functools.partial(ydl.extract_info, url, False))
                print(f"[playlist] yt-dlp extraction finished for url: {url}", flush=True)
                return info
            try:
                info = await asyncio.wait_for(fetch_info(), timeout=30)
                print(f"[playlist] yt-dlp info received", flush=True)
                entries = info.get('entries')
                if not entries:
                    print(f"[playlist] No playlist entries found for url: {url}", flush=True)
                    await ctx.followup.send('No playlist found for this URL.')
                    return
                added_count = 0
                for entry in entries:
                    audio_formats = sorted(
                        [f for f in entry['formats'] if f.get('acodec') != 'none' and f.get('url')],
                        key=lambda x: 0 if x.get('abr') is None else x.get('abr'),
                        reverse=True
                    )
                    if not audio_formats:
                        continue
                    stream_url = audio_formats[0]['url']
                    title = entry.get('title', 'Unknown Title')
                    webpage_url = entry.get('webpage_url', url)
                    if len(guild_queues[guild_id]) < QUEUE_LIMIT:
                        guild_queues[guild_id].append({'url': stream_url, 'title': title, 'ctx': ctx, 'webpage_url': webpage_url})
                        added_count += 1
                print(f"[playlist] Added {added_count} videos to queue (guild={guild_id})", flush=True)
                await ctx.followup.send(f'Added {added_count} videos to queue.')
                if not guild_playing[guild_id] and added_count > 0:
                    print(f"[playlist] Starting playback for guild {guild_id}", flush=True)
                    await play_next(ctx)
            except asyncio.TimeoutError:
                print(f"[playlist] Timeout during yt-dlp extraction for url: {url}", flush=True)
                await ctx.followup.send('Timeout: 유튜브 플레이리스트 정보 추출이 30초 내에 완료되지 않았습니다.')
                return
            except Exception as e:
                print(f"[playlist] Exception during yt-dlp extraction: {e}", flush=True)
                await ctx.followup.send(f'Failed to fetch playlist: {e}')
                return
        except Exception as e:
            print(f"[playlist] Unexpected error: {e}", flush=True)
            await ctx.followup.send(f'Unexpected error: {e}')

    # === 음악 명령어: 현재 곡 반복 ===
    @bot.slash_command(guild_id=[1345392235264348170, 540157160961867796, 326024303948857356], description="Repeat the current song.")
    async def repeat(ctx):
        guild_id = ctx.guild.id
        song = current_song.get(guild_id)
        if song:
            guild_queues[guild_id].appendleft({'url': song['url'], 'title': song['title'], 'ctx': ctx})
            await ctx.respond(f'Repeated: {song["title"]}')
        else:
            await ctx.respond('No song is currently playing.')

    # === 음악 명령어: 큐 셔플 ===
    @bot.slash_command(guild_id=[1345392235264348170, 540157160961867796, 326024303948857356], description="Shuffle the music queue.")
    async def shuffle(ctx):
        guild_id = ctx.guild.id
        q = guild_queues.get(guild_id, deque())
        if len(q) < 2:
            await ctx.respond('Not enough songs in queue to shuffle.')
            return
        random.shuffle(q)
        await ctx.respond('Queue shuffled.')

    # === 음악 명령어: 곡 스킵 ===
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

    # === 음악 명령어: 곡 일시정지 ===
    @bot.slash_command(guild_id=[1345392235264348170, 540157160961867796, 326024303948857356], description="Pause the current song.")
    async def pause(ctx):
        voice_client = ctx.voice_client
        if voice_client and voice_client.is_playing():
            voice_client.pause()
            await ctx.respond('Playback paused.')
        else:
            await ctx.respond('Nothing is playing right now.')

    # === 음악 명령어: 곡 재개 ===
    @bot.slash_command(guild_id=[1345392235264348170, 540157160961867796, 326024303948857356], description="Resume the paused song.")
    async def resume(ctx):
        voice_client = ctx.voice_client
        if voice_client and voice_client.is_paused():
            voice_client.resume()
            await ctx.respond('Playback resumed.')
        else:
            await ctx.respond('Nothing is paused right now.')

    # === 음악 명령어: 큐 보기 ===
    @bot.slash_command(guild_id=[1345392235264348170, 540157160961867796, 326024303948857356], description="Show the current music queue.")
    async def queue(ctx):
        guild_id = ctx.guild.id
        q = get_guild_queue(guild_id)
        if not q:
            await ctx.respond('Queue is empty.')
        else:
            msg = '\n'.join([f'{i+1}. {item["title"]}' for i, item in enumerate(q)])
            await ctx.respond(f'Current queue:\n{msg}')

    # === 음악 명령어: 큐에서 곡 제거 ===
    @bot.slash_command(guild_id=[1345392235264348170, 540157160961867796, 326024303948857356], description="Remove a song from the queue by its position.")
    async def remove(ctx, position: int):
        guild_id = ctx.guild.id
        removed = remove_from_queue(guild_id, position)
        if removed:
            await ctx.respond(f'Removed from queue: {removed}')
        else:
            await ctx.respond('Queue is empty or invalid position.')

    # === 음악 명령어: 큐 전체 비우기 ===
    @bot.slash_command(guild_id=[1345392235264348170, 540157160961867796, 326024303948857356], description="Clear the entire music queue.")
    async def clear(ctx):
        guild_id = ctx.guild.id
        if is_queue_empty(guild_id):
            await ctx.respond('Queue is already empty.')
        else:
            clear_guild_queue(guild_id)
            await ctx.respond('Queue cleared.')

    # === 음악 명령어: 현재 재생 중인 곡 정보 ===
    @bot.slash_command(guild_id=[1345392235264348170, 540157160961867796, 326024303948857356], description="Show info about the currently playing song.")
    async def nowplaying(ctx):
        guild_id = ctx.guild.id
        song = current_song.get(guild_id)
        if song:
            await ctx.respond(f'Now playing: {song["title"]}\nURL: {song["url"]}')
        else:
            await ctx.respond('No song is currently playing.')

    # === 음악 명령어: 음성 채널에서 봇 퇴장 ===
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

    # === 음악 명령어: 유튜브 단일 곡 재생 ===
    @bot.slash_command(guild_id=[1345392235264348170, 540157160961867796, 326024303948857356], description="Play a song from YouTube.")
    async def play(ctx, url: str):
        guild_id = ctx.guild.id
        await ctx.defer()
        try:
            print(f"[play] Command received: guild={guild_id}, url={url}", flush=True)
            if guild_id not in guild_queues:
                guild_queues[guild_id] = deque()
                guild_playing[guild_id] = False
                print(f"[play] Initialized queue and playing state for guild {guild_id}", flush=True)
            # queue 길이 제한 체크
            if len(guild_queues[guild_id]) >= QUEUE_LIMIT:
                print(f"[play] Queue full for guild {guild_id}", flush=True)
                await ctx.followup.send(f'Queue is full! (최대 {QUEUE_LIMIT}곡까지 가능)')
                return
            if not ctx.voice_client:
                if ctx.author.voice:
                    channel = ctx.author.voice.channel
                    try:
                        print(f"[play] Connecting to voice channel: {channel}", flush=True)
                        await channel.connect()
                        print(f"[play] Connected to voice channel: {channel}", flush=True)
                    except Exception as e:
                        print(f"[play] Failed to connect to voice channel: {e}", flush=True)
                        await ctx.followup.send(f'Failed to connect to voice channel: {e}')
                        return
                else:
                    print(f"[play] Author not in voice channel", flush=True)
                    await ctx.followup.send("You need to be in a voice channel to play music.")
                    return
            ydl_opts = {
                'format': 'bestaudio',
                'quiet': False,
                'noplaylist': True,
            }
            # ...existing code...
            async def fetch_info():
                loop = asyncio.get_event_loop()
                print(f"[play] Starting yt-dlp extraction for url: {url}", flush=True)
                with youtube_dl.YoutubeDL(ydl_opts) as ydl:
                    info = await loop.run_in_executor(None, functools.partial(ydl.extract_info, url, False))
                print(f"[play] yt-dlp extraction finished for url: {url}", flush=True)
                return info
            try:
                info = await asyncio.wait_for(fetch_info(), timeout=15)
                print(f"[play] yt-dlp info received: title={info.get('title', 'Unknown')}", flush=True)
                audio_formats = sorted(
                    [f for f in info['formats'] if f.get('acodec') != 'none' and f.get('url')],
                    key=lambda x: 0 if x.get('abr') is None else x.get('abr'),
                    reverse=True
                )
                if not audio_formats:
                    print(f"[play] No audio stream found for url: {url}", flush=True)
                    await ctx.followup.send('No audio stream found for this video.')
                    return
                stream_url = audio_formats[0]['url']
                title = info.get('title', 'Unknown Title')
                webpage_url = info.get('webpage_url', url)
                guild_queues[guild_id].append({'url': stream_url, 'title': title, 'ctx': ctx, 'webpage_url': webpage_url})
                print(f"[play] Added to queue: {title} (guild={guild_id})", flush=True)
                await ctx.followup.send(f'Added to queue: {title}')
                if not guild_playing[guild_id]:
                    print(f"[play] Starting playback for guild {guild_id}", flush=True)
                    await play_next(ctx)
            except asyncio.TimeoutError:
                print(f"[play] Timeout during yt-dlp extraction for url: {url}", flush=True)
                await ctx.followup.send('Timeout: 유튜브 정보 추출이 15초 내에 완료되지 않았습니다.')
                return
            except Exception as e:
                print(f"[play] Exception during yt-dlp extraction: {e}", flush=True)
                await ctx.followup.send(f'Failed to fetch audio: {e}')
                return
        except Exception as e:
            print(f"[play] Unexpected error: {e}", flush=True)
            await ctx.followup.send(f'Unexpected error: {e}')


# === play_next를 전역 함수로 분리 ===
async def play_next(ctx):
    guild_id = ctx.guild.id
    try:
        print(f"[play_next] Called for guild {guild_id}", flush=True)
        if guild_queues[guild_id]:
            next_song = guild_queues[guild_id].popleft()
            voice_client = ctx.voice_client
            guild_playing[guild_id] = True
            # 현재 곡 정보 저장
            display_url = next_song.get('webpage_url', next_song['url'])
            current_song[guild_id] = {'title': next_song['title'], 'url': display_url}
            print(f"[play_next] Now playing: {next_song['title']} (guild={guild_id})", flush=True)
            def after_playing(error):
                print(f"[play_next] Song finished: {next_song['title']} (guild={guild_id}), error={error}", flush=True)
                coro = play_next(next_song['ctx'])
                asyncio.run_coroutine_threadsafe(coro, main_loop)
            try:
                print(f"[play_next] Starting FFmpegPCMAudio for url: {next_song['url']}", flush=True)
                source = discord.FFmpegPCMAudio(
                    next_song['url'],
                    before_options='-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -probesize 32M',
                    options='-vn'
                )
                voice_client.play(source, after=after_playing)
                print(f"[play_next] Playback started for: {next_song['title']} (guild={guild_id})", flush=True)
            except Exception as e:
                print(f"[play_next] Failed to play audio: {e}", flush=True)
                await next_song['ctx'].respond(f'Failed to play audio: {e}')
                guild_playing[guild_id] = False
                current_song[guild_id] = None
                return
            coro = next_song['ctx'].respond(f'Now playing: {next_song["title"]}\nURL: {display_url}')
            asyncio.run_coroutine_threadsafe(coro, main_loop)
        else:
            print(f"[play_next] Queue empty for guild {guild_id}", flush=True)
            # 자동재생이 켜져 있으면 유튜브 추천곡에서 다음 곡을 찾아 재생
            if autoplay_enabled.get(guild_id, False) and current_song.get(guild_id):
                last_url = current_song[guild_id]['url']
                print(f"[autoplay] Trying to fetch related video for url: {last_url}", flush=True)
                ydl_opts = {
                    'format': 'bestaudio',
                    'quiet': True,
                    'noplaylist': True,
                }
                async def fetch_related():
                    loop = asyncio.get_event_loop()
                    with youtube_dl.YoutubeDL(ydl_opts) as ydl:
                        info = await loop.run_in_executor(None, functools.partial(ydl.extract_info, last_url, False))
                    return info
                try:
                    info = await asyncio.wait_for(fetch_related(), timeout=15)
                    related = info.get('related_videos')
                    if related:
                        # 가장 첫 번째 추천 영상의 id로 url 생성
                        next_id = related[0].get('id')
                        if next_id:
                            next_url = f'https://www.youtube.com/watch?v={next_id}'
                            print(f"[autoplay] Found related video: {next_url}", flush=True)
                            # play 명령어와 동일하게 큐에 추가 후 재생
                            await ctx.invoke(ctx.bot.get_slash_command('play'), url=next_url)
                            # current_song/guild_playing은 play에서 처리됨
                            return
                    print(f"[autoplay] No related videos found.", flush=True)
                    await ctx.respond('Autoplay: 추천곡을 찾지 못했습니다.')
                except Exception as e:
                    print(f"[autoplay] Failed to fetch related video: {e}", flush=True)
                    await ctx.respond(f'Autoplay: 추천곡을 가져오지 못했습니다: {e}')
            guild_playing[guild_id] = False
            current_song[guild_id] = None
    except Exception as e:
        print(f"[play_next] Unexpected error: {e}", flush=True)
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
                    for entry in guild_queues[guild_id]:
                        webpage_url = entry.get('webpage_url', entry['url'])
                guild_queues[guild_id].clear()
