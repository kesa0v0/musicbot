import discord
import asyncio
import yt_dlp as youtube_dl
import functools
from collections import deque
from utils import get_related_videos
import logging

logger = logging.getLogger(__name__)


# yt-dlp와 FFmpeg 옵션 설정
YDL_OPTS = {
    'format': 'bestaudio[ext=m4a]/bestaudio/best',
    'quiet': True,
    'noplaylist': True,
}
FFMPEG_OPTS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -analyzeduration 8M -probesize 32M',
    'options': '-vn',
}
QUEUE_LIMIT = 30

class GuildState:
    """각 서버(길드)의 상태를 관리하는 클래스"""
    def __init__(self, loop):
        self.loop = loop
        self.queue = deque()
        self.current_song = None
        self.is_playing = False
        self.autoplay_enabled = True # 자동재생 기본값

class MusicCog(discord.Cog):
    """음악 기능 관련 모든 로직을 담는 Cog 클래스"""
    def __init__(self, bot):
        self.bot = bot
        self.states = {} # {guild_id: GuildState}

    def _get_state(self, guild_id) -> GuildState:
        """해당 길드의 상태 객체를 가져오거나 새로 생성합니다."""
        if guild_id not in self.states:
            self.states[guild_id] = GuildState(self.bot.loop)
        return self.states[guild_id]

    async def _prefetch_next_song(self, guild_id):
        """큐의 다음 곡을 미리 준비(프리페칭)합니다."""
        state = self._get_state(guild_id)
        if not state.queue:
            return

        next_song = state.queue[0]
        if next_song.get('prefetched', False):
            return

        logger.info(f"[prefetch] Starting for: {next_song['title']}")
        try:
            with youtube_dl.YoutubeDL(YDL_OPTS) as ydl:
                info = await self.bot.loop.run_in_executor(None, functools.partial(ydl.extract_info, next_song['webpage_url'], download=False))
            
            audio_formats = sorted([f for f in info['formats'] if f.get('acodec') != 'none' and f.get('url')], key=lambda x: 0 if x.get('abr') is None else x.get('abr'), reverse=True)

            if audio_formats:
                stream_url = audio_formats[0]['url']
                state.queue[0]['url'] = stream_url
                state.queue[0]['prefetched'] = True
                logger.info(f"[prefetch] Success for: {next_song['title']}")
        except Exception as e:
            logger.error(f"[prefetch] Failed for {next_song['title']}: {e}")

    async def _play_next(self, ctx):
        """
        큐의 다음 곡을 재생합니다. 큐가 비었으면 자동재생을 시도합니다.
        이 함수는 모든 재생 로직의 중심입니다.
        """
        guild_id = ctx.guild.id
        state = self._get_state(guild_id)

        # 1. 큐가 비어있는 경우, 자동재생을 시도합니다.
        if not state.queue:
            logger.info(f"[_play_next] Queue is empty.")
            if state.autoplay_enabled and state.current_song:
                last_url = state.current_song['webpage_url']
                logger.info(f"[autoplay] Triggered. Fetching recommendations based on: {last_url}")
                import re
                match = re.search(r"v=([\w-]+)", last_url)
                video_id = match.group(1) if match else None
                if video_id:
                    try:
                        # utils.py의 함수를 직접 호출
                        related_videos = get_related_videos(video_id, max_results=3)
                        if related_videos:
                            for video_info in related_videos:
                                if isinstance(video_info, dict) and video_info.get('id'):
                                    video_id = video_info.get('id')
                                    title = video_info.get('title', 'Unknown Title')
                                    url = f"https://www.youtube.com/watch?v={video_id}"
                                    state.queue.append({'url': url, 'title': title, 'ctx': ctx, 'webpage_url': url, 'prefetched': False, 'added_by': 'autoplay'})
                            
                            if state.queue:
                                logger.info(f"[autoplay] Added {len(related_videos)} songs. Restarting _play_next.")
                                await self._play_next(ctx)
                                return
                        else:
                            await ctx.channel.send('Autoplay: 추천곡을 찾지 못했습니다.')
                    except Exception as e:
                        logger.error(f"[autoplay] Exception: {e}")
                        await ctx.channel.send(f'Autoplay: 추천곡 재생 중 오류가 발생했습니다: {e}')
            
            logger.info(f"[_play_next] Stopping playback.")
            state.is_playing = False
            state.current_song = None
            return

        # 2. 큐에 곡이 있으면, 다음 곡을 재생합니다.
        next_song = state.queue.popleft()
        voice_client = ctx.voice_client
        if not voice_client or not voice_client.is_connected():
            state.is_playing = False
            return

        play_url = next_song.get('url')
        if not next_song.get('prefetched', False):
            logger.info(f"[_play_next] Song not prefetched. Fetching stream URL for: {next_song['title']}")
            try:
                with youtube_dl.YoutubeDL(YDL_OPTS) as ydl:
                    info = await self.bot.loop.run_in_executor(None, functools.partial(ydl.extract_info, next_song['webpage_url'], download=False))
                audio_formats = sorted([f for f in info['formats'] if f.get('acodec') != 'none' and f.get('url')], key=lambda x: 0 if x.get('abr') is None else x.get('abr'), reverse=True)
                if not audio_formats:
                    raise ValueError("No suitable audio stream found")
                play_url = audio_formats[0]['url']
                logger.info(f"[_play_next] Stream URL fetched successfully.")
            except Exception as e:
                logger.error(f"[_play_next] Failed to fetch stream URL for {next_song['title']}: {e}")
                await ctx.channel.send(f"'{next_song['title']}'을(를) 재생할 수 없어 건너뜁니다.")
                await self._play_next(ctx)
                return

        state.is_playing = True
        state.current_song = next_song
        
        def after_playing(error):
            if error:
                logger.error(f"[_play_next:after] Error playing {next_song['title']}: {error}")
            # self.bot.loop를 사용하여 코루틴을 스레드 안전하게 실행
            self.bot.loop.create_task(self._play_next(ctx))

        try:
            source = discord.FFmpegPCMAudio(play_url, **FFMPEG_OPTS)
            voice_client.play(source, after=after_playing)
            await ctx.channel.send(f'Now playing: {next_song["title"]}\nURL: {next_song["webpage_url"]}')

            # 3. 재생 시작 후, 다음 곡이 있다면 프리페칭합니다.
            if state.queue:
                self.bot.loop.create_task(self._prefetch_next_song(guild_id))

        except Exception as e:
            logger.critical(f"[_play_next] Critical error trying to play {next_song['title']}: {e}")
            await ctx.channel.send(f"'{next_song['title']}' 재생 중 심각한 오류가 발생했습니다.")
            await self._play_next(ctx)

    # --- 사용자 명령어 ---

    @discord.slash_command(description="음악봇 명령어 도움말을 보여줍니다.")
    async def help(self, ctx):
        help_text = (
            "**[음악봇 명령어 안내]**\n"
            "/play <url 또는 검색어> : 노래를 큐에 추가 및 재생\n"
            "/playlist <url> : 유튜브 플레이리스트 전체 추가\n"
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
        await ctx.respond(help_text, ephemeral=True)

    @discord.slash_command(description="노래를 재생하거나 큐에 추가합니다.")
    async def play(self, ctx, query: str):
        logger.info(f"[play] Received query: {query}")
        await ctx.defer()
        state = self._get_state(ctx.guild.id)

        # 사용자 우선 로직: 자동재생으로 추가된 곡들을 큐에서 제거합니다.
        if any(song.get('added_by') == 'autoplay' for song in state.queue):
            state.queue = deque(song for song in state.queue if song.get('added_by') != 'autoplay')
            logger.info(f"[play] User interrupted autoplay. Clearing autoplay songs from queue.")
            await ctx.channel.send("자동재생 목록을 지웠습니다. 요청하신 곡을 우선 재생합니다.", delete_after=10)

        try:
            if len(state.queue) >= QUEUE_LIMIT:
                await ctx.followup.send(f'큐가 가득 찼습니다! (최대 {QUEUE_LIMIT}곡)')
                return

            if not ctx.voice_client:
                if ctx.author.voice:
                    await ctx.author.voice.channel.connect()
                else:
                    await ctx.followup.send("음성 채널에 먼저 참여해주세요.")
                    return
            
            # 검색어 지원
            search_query = f"ytsearch:{query}" if not query.startswith('http') else query
            
            with youtube_dl.YoutubeDL({'quiet': True, 'noplaylist': True, 'default_search': 'ytsearch'}) as ydl:
                info = await self.bot.loop.run_in_executor(None, functools.partial(ydl.extract_info, search_query, download=False))
            
            # 검색 결과가 리스트일 경우 첫 번째 항목 사용
            if 'entries' in info:
                info = info['entries'][0]

            title = info.get('title', 'Unknown Title')
            webpage_url = info.get('webpage_url', query)

            state.queue.append({'url': webpage_url, 'title': title, 'ctx': ctx, 'webpage_url': webpage_url, 'added_by': 'user', 'prefetched': False})
            await ctx.followup.send(f'큐에 추가됨: {title}')
            
            if not state.is_playing:
                await self._play_next(ctx)

        except Exception as e:
            logger.error(f"[play] Unexpected error: {e}")
            await ctx.followup.send(f'오류가 발생했습니다: {e}')

    @discord.slash_command(description="유튜브 플레이리스트를 큐에 추가합니다.")
    async def playlist(self, ctx, url: str):
        await ctx.defer()
        state = self._get_state(ctx.guild.id)

        if any(song.get('added_by') == 'autoplay' for song in state.queue):
            state.queue = deque(song for song in state.queue if song.get('added_by') != 'autoplay')
            logger.info(f"[playlist] User interrupted autoplay. Clearing autoplay songs.")
            await ctx.channel.send("자동재생 목록을 지웠습니다. 요청하신 재생목록을 우선 추가합니다.", delete_after=10)

        try:
            if not ctx.voice_client:
                if ctx.author.voice:
                    await ctx.author.voice.channel.connect()
                else:
                    await ctx.followup.send("음성 채널에 먼저 참여해주세요.")
                    return

            with youtube_dl.YoutubeDL({'quiet': True, 'noplaylist': False, 'extract_flat': True}) as ydl:
                info = await self.bot.loop.run_in_executor(None, functools.partial(ydl.extract_info, url, download=False))
            
            entries = info.get('entries')
            if not entries:
                await ctx.followup.send('플레이리스트를 찾을 수 없거나, 비어있습니다.')
                return
            
            added_count = 0
            for entry in entries:
                if not entry or not entry.get('id'):
                    continue
                if len(state.queue) >= QUEUE_LIMIT:
                    break
                title = entry.get('title', 'Unknown Title')
                webpage_url = f"https://www.youtube.com/watch?v={entry['id']}"
                state.queue.append({'url': webpage_url, 'title': title, 'ctx': ctx, 'webpage_url': webpage_url, 'added_by': 'user', 'prefetched': False})
                added_count += 1

            await ctx.followup.send(f'{added_count}개의 노래를 큐에 추가했습니다.')
            
            if not state.is_playing and added_count > 0:
                await self._play_next(ctx)
        except Exception as e:
            logger.error(f"플레이리스트를 가져오는 중 오류가 발생했습니다: {e}")
            await ctx.followup.send(f'플레이리스트를 가져오는 중 오류가 발생했습니다: {e}')

    @discord.slash_command(description="현재 재생 중인 노래를 건너뜁니다.")
    async def skip(self, ctx):
        voice_client = ctx.voice_client
        if voice_client and voice_client.is_playing():
            voice_client.stop()
            await ctx.respond('노래를 건너뛰었습니다.', ephemeral=True)
        else:
            await ctx.respond('재생 중인 노래가 없습니다.', ephemeral=True)

    @discord.slash_command(description="재생을 일시정지합니다.")
    async def pause(self, ctx):
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.pause()
            await ctx.respond("재생을 일시정지했습니다.", ephemeral=True)
        else:
            await ctx.respond("재생 중인 노래가 없습니다.", ephemeral=True)

    @discord.slash_command(description="일시정지된 재생을 재개합니다.")
    async def resume(self, ctx):
        if ctx.voice_client and ctx.voice_client.is_paused():
            ctx.voice_client.resume()
            await ctx.respond("재생을 재개했습니다.", ephemeral=True)
        else:
            await ctx.respond("일시정지된 노래가 없습니다.", ephemeral=True)

    @discord.slash_command(description="재생 대기열을 보여줍니다.")
    async def queue(self, ctx):
        state = self._get_state(ctx.guild.id)
        if not state.queue:
            await ctx.respond('큐가 비어있습니다.', ephemeral=True)
            return

        msg_lines = []
        for i, item in enumerate(state.queue, 1):
            line = f'{i}. {item["title"]}'
            if item.get('added_by') == 'autoplay':
                line += " (추천)"
            msg_lines.append(line)
            if i >= 15:
                msg_lines.append(f"... 외 {len(state.queue) - 15}곡")
                break
        
        await ctx.respond(f'**현재 대기열:**\n' + '\n'.join(msg_lines))

    @discord.slash_command(description="대기열에서 특정 노래를 제거합니다.")
    async def remove(self, ctx, position: int):
        state = self._get_state(ctx.guild.id)
        if not state.queue or not (1 <= position <= len(state.queue)):
            await ctx.respond("잘못된 번호입니다.", ephemeral=True)
            return
        
        removed = state.queue[position-1]
        del state.queue[position-1]
        await ctx.respond(f'큐에서 제거됨: {removed["title"]}')

    @discord.slash_command(description="대기열을 모두 비웁니다.")
    async def clear(self, ctx):
        state = self._get_state(ctx.guild.id)
        if state.queue:
            state.queue.clear()
            await ctx.respond("큐를 모두 비웠습니다.")
        else:
            await ctx.respond("큐가 이미 비어있습니다.", ephemeral=True)

    @discord.slash_command(description="현재 재생 중인 노래 정보를 보여줍니다.")
    async def nowplaying(self, ctx):
        state = self._get_state(ctx.guild.id)
        if state.current_song:
            await ctx.respond(f'현재 재생 중: {state.current_song["title"]}\nURL: {state.current_song["webpage_url"]}')
        else:
            await ctx.respond("재생 중인 노래가 없습니다.", ephemeral=True)

    @discord.slash_command(description="음성 채널에서 나갑니다.")
    async def leave(self, ctx):
        state = self._get_state(ctx.guild.id)
        if ctx.voice_client:
            await ctx.voice_client.disconnect()
            state.is_playing = False
            state.queue.clear()
            await ctx.respond("음성 채널을 나갔습니다.")
        else:
            await ctx.respond("음성 채널에 연결되어 있지 않습니다.", ephemeral=True)

    @discord.slash_command(description="자동재생 기능을 켜거나 끕니다.")
    async def autoplay(self, ctx, mode: str):
        state = self._get_state(ctx.guild.id)
        mode = mode.lower()
        if mode == "on":
            state.autoplay_enabled = True
            await ctx.respond("자동재생이 켜졌습니다.")
        elif mode == "off":
            state.autoplay_enabled = False
            await ctx.respond("자동재생이 꺼졌습니다.")
        else:
            await ctx.respond("사용법: /autoplay on 또는 /autoplay off", ephemeral=True)

def setup(bot):
    bot.add_cog(MusicCog(bot))