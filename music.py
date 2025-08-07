import discord
import asyncio
import yt_dlp as youtube_dl
import functools
from collections import deque
from utils import get_related_videos
import logging
import random
import discord.ui

logger = logging.getLogger(__name__)


# yt-dlp와 FFmpeg 옵션 설정
YDL_OPTS = {
    'format': 'bestaudio[ext=m4a]/bestaudio/best',
    'quiet': True,
    'noplaylist': True,
    'source_address': '0.0.0.0', # Force IPv4
}
FFMPEG_OPTS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -analyzeduration 8M -probesize 32M',
    'options': '-vn -af loudnorm=I=-16:TP=-1.5:LRA=11',
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
        self.played_history = deque(maxlen=20) # 최근 재생된 곡 ID 저장
        self.loop_mode = "off" # "off", "current", "queue"

class SongSelectionView(discord.ui.View):
    def __init__(self, entries, original_ctx, timeout=30):
        super().__init__(timeout=timeout)
        self.entries = entries
        self.selected_entry = None
        self.original_ctx = original_ctx

        # 버튼 추가
        for i, entry in enumerate(entries):
            button = discord.ui.Button(label=str(i+1), style=discord.ButtonStyle.primary, custom_id=f"select_song_{i}")
            button.callback = self.create_callback(entry)
            self.add_item(button)
        
        # 취소 버튼 추가
        cancel_button = discord.ui.Button(label="취소", style=discord.ButtonStyle.danger, custom_id="cancel_selection")
        cancel_button.callback = self.cancel_callback
        self.add_item(cancel_button)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        await self.message.edit(content="곡 선택 시간이 초과되었습니다.", view=self)
        self.stop()

    def create_callback(self, entry):
        async def callback(interaction: discord.Interaction):
            if interaction.user != self.original_ctx.author:
                await interaction.response.send_message("이 버튼은 당신을 위한 것이 아닙니다.", ephemeral=True)
                return
            self.selected_entry = entry
            for item in self.children:
                item.disabled = True
            await interaction.response.edit_message(content=f"'{entry.get('title', 'Unknown Title')}'을(를) 선택했습니다.", view=self)
            self.stop()
        return callback

    async def cancel_callback(self, interaction: discord.Interaction):
        if interaction.user != self.original_ctx.author:
            await interaction.response.send_message("이 버튼은 당신을 위한 것이 아닙니다.", ephemeral=True)
            return
        self.selected_entry = None # 선택 취소
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="곡 선택이 취소되었습니다.", view=self)
        self.stop()

class MusicCog(discord.Cog):
    """음악 기능 관련 모든 로직을 담는 Cog 클래스"""
    def __init__(self, bot):
        self.bot = bot
        self.states = {} # {guild_id: GuildState}

    async def _check_and_leave(self, guild_id):
        state = self._get_state(guild_id)
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return

        voice_client = guild.voice_client
        if voice_client and voice_client.is_connected():
            # 봇 외에 다른 사람이 음성 채널에 없는지 확인
            human_members = [m for m in voice_client.channel.members if not m.bot]
            if not human_members:
                logger.info(f"[auto-leave] Leaving voice channel in guild {guild_id} due to inactivity.")
                await voice_client.disconnect()
                state.is_playing = False
                state.current_song = None
                if guild_id in self.states:
                    del self.states[guild_id] # 길드 상태 정리

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

    async def _schedule_autoplay_if_needed(self, guild_id, ctx):
        """현재 곡 재생 직후, 큐가 비어있다면 다음 자동재생 곡을 미리 준비합니다."""
        await asyncio.sleep(1) # state.current_song이 확실히 설정되도록 잠시 대기
        state = self._get_state(guild_id)

        # 큐에 노래가 있거나, 자동재생이 꺼져있으면 아무것도 안 함
        if state.queue or not state.autoplay_enabled or not state.current_song:
            return

        logger.info(f"[pre-emptive-autoplay] Queue is empty. Scheduling next song.")
        
        last_url = state.current_song['webpage_url']
        import re
        match = re.search(r"v=([\w-]+)", last_url)
        video_id = match.group(1) if match else None

        if video_id:
            try:
                related_videos = await self.bot.loop.run_in_executor(
                    None, functools.partial(get_related_videos, video_id, max_results=10)
                )
                if related_videos:
                    # 현재 큐에 있는 곡들의 ID와 재생 기록에 있는 곡들의 ID를 수집
                    current_queue_ids = {re.search(r"v=([\w-]+)", song['webpage_url']).group(1) for song in state.queue if re.search(r"v=([\w-]+)", song['webpage_url'])}
                    played_history_ids = set(state.played_history)
                    
                    # 필터링된 추천곡 목록 생성
                    filtered_videos = [
                        v for v in related_videos 
                        if v.get('id') and v['id'] not in current_queue_ids and v['id'] not in played_history_ids
                    ]

                    if filtered_videos:
                        video_info = random.choice(filtered_videos) # 무작위로 하나 선택
                        video_id = video_info.get('id')
                        title = video_info.get('title', 'Unknown Title')
                        url = f"https://www.youtube.com/watch?v={video_id}"
                        
                        # 큐에 추가하고 바로 프리페치 실행
                        state.queue.append({'url': url, 'title': title, 'ctx': ctx, 'webpage_url': url, 'prefetched': False, 'added_by': 'autoplay'})
                        logger.info(f"[pre-emptive-autoplay] Added '{title}'. Now prefetching.")
                        await self._prefetch_next_song(guild_id)
                    else:
                        logger.info("[pre-emptive-autoplay] No new related videos found after filtering.")

            except Exception as e:
                logger.error(f"[pre-emptive-autoplay] Failed: {e}")


    async def _play_next(self, ctx):
        logger.debug(f"[_play_next] Function called for guild: {ctx.guild.id}")
        """
        큐의 다음 곡을 재생합니다. 큐가 비었으면 자동재생을 시도합니다.
        이 함수는 모든 재생 로직의 중심입니다.
        """
        guild_id = ctx.guild.id
        state = self._get_state(guild_id)

        # 1. 큐가 비어있는 경우, 자동재생을 시도합니다. (안전장치)
        if not state.queue:
            logger.info(f"[_play_next] Queue is empty, attempting autoplay as a fallback.")
            if state.autoplay_enabled and state.current_song:
                last_url = state.current_song['webpage_url']
                logger.info(f"[autoplay] Triggered. Fetching recommendation based on: {last_url}")
                import re
                match = re.search(r"v=([\w-]+)", last_url)
                video_id = match.group(1) if match else None
                if video_id:
                    try:
                        # 관련 동영상을 1개만 가져옵니다.
                        related_videos = await self.bot.loop.run_in_executor(
                            None, functools.partial(get_related_videos, video_id, max_results=10)
                        )
                        if related_videos:
                            # 현재 큐에 있는 곡들의 ID와 재생 기록에 있는 곡들의 ID를 수집
                            current_queue_ids = {re.search(r"v=([\w-]+)", song['webpage_url']).group(1) for song in state.queue if re.search(r"v=([\w-]+)", song['webpage_url'])}
                            played_history_ids = set(state.played_history)

                            # 필터링된 추천곡 목록 생성
                            filtered_videos = [
                                v for v in related_videos 
                                if v.get('id') and v['id'] not in current_queue_ids and v['id'] not in played_history_ids
                            ]

                            if filtered_videos:
                                video_info = random.choice(filtered_videos) # 무작위로 하나 선택
                                if isinstance(video_info, dict) and video_info.get('id'):
                                    new_video_id = video_info.get('id')
                                    title = video_info.get('title', 'Unknown Title')
                                    url = f"https://www.youtube.com/watch?v={new_video_id}"
                                    
                                    state.queue.append({'url': url, 'title': title, 'ctx': ctx, 'webpage_url': url, 'prefetched': False, 'added_by': 'autoplay'})
                                    logger.info(f"[autoplay] Added '{title}' to the queue.")
                                else:
                                    logger.warning("[autoplay] Found related video, but it has invalid data.")
                            else:
                                logger.info("[autoplay] No new related videos found after filtering.")
                        else:
                            logger.info("[autoplay] No related videos found.")
                    except Exception as e:
                        logger.error(f"[autoplay] Exception: {e}")

            if not state.queue:
                logger.info(f"[_play_next] Stopping playback as queue is still empty.")
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
            
            # 현재 곡의 video_id를 played_history에 추가
            if next_song.get('webpage_url'):
                import re
                match = re.search(r"v=([\w-]+)", next_song['webpage_url'])
                video_id = match.group(1) if match else None
                if video_id:
                    state.played_history.append(video_id)
                    logger.info(f"[autoplay] Added {video_id} to played history.")

            # 반복 모드 처리
            if state.loop_mode == "current":
                # 현재 곡을 큐의 맨 앞에 다시 추가하여 반복
                state.queue.appendleft(next_song)
                logger.info(f"[loop] Looping current song: {next_song['title']}")
            elif state.loop_mode == "queue":
                # 현재 곡을 큐의 맨 뒤에 다시 추가하여 큐 반복
                state.queue.append(next_song)
                logger.info(f"[loop] Looping queue. Added {next_song['title']} to end of queue.")

            self.bot.loop.create_task(self._play_next(ctx))

        try:
            source = discord.FFmpegPCMAudio(play_url, **FFMPEG_OPTS)
            voice_client.play(source, after=after_playing)
            await ctx.channel.send(f'Now playing: {next_song["title"]}\nURL: {next_song["webpage_url"]}')

            # 3. 재생 시작 후, 다음 곡을 선제적으로 준비합니다.
            # 사용자가 추가한 곡이 있으면 그것을 프리페치하고, 없으면 자동재생 곡을 준비합니다.
            if state.queue:
                self.bot.loop.create_task(self._prefetch_next_song(guild_id))
            else:
                self.bot.loop.create_task(self._schedule_autoplay_if_needed(guild_id, ctx))

        except Exception as e:
            logger.exception(f"[_play_next] Critical error trying to play {next_song['title']}")
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
                    logger.debug(f"[play] Attempting to connect to voice channel: {ctx.author.voice.channel.name}")
                    await ctx.author.voice.channel.connect()
                    logger.debug(f"[play] Successfully connected to voice channel: {ctx.author.voice.channel.name}")
                else:
                    logger.debug("[play] User not in a voice channel.")
                    await ctx.followup.send("음성 채널에 먼저 참여해주세요.")
                    return
            else:
                logger.debug("[play] Bot already connected to a voice channel.")

            # 검색어 지원
            search_query = f"ytsearch5:{query}" if not query.startswith('http') else query
            
            ydl_opts = {'quiet': True, 'noplaylist': True, 'default_search': 'ytsearch', 'source_address': '0.0.0.0'}
            with youtube_dl.YoutubeDL(ydl_opts) as ydl:
                info = await self.bot.loop.run_in_executor(None, functools.partial(ydl.extract_info, search_query, download=False))
            
            # 검색 결과가 리스트일 경우 첫 번째 항목 사용
            if 'entries' in info:
                # 검색 결과가 여러 개일 경우, SongSelectionView를 사용하여 사용자에게 선택지를 제공
                entries = [e for e in info['entries'] if e and e.get('id')][:5] # 최대 5개 결과
                if not entries:
                    await ctx.followup.send(f"'{query}'에 대한 검색 결과를 찾을 수 없습니다.")
                    return

                msg = "다음 중 재생할 곡을 선택해주세요:\n"
                for i, entry in enumerate(entries):
                    msg += f"{i+1}. {entry.get('title', 'Unknown Title')}\n"

                view = SongSelectionView(entries, ctx)
                message = await ctx.followup.send(msg, view=view)
                view.message = message # view에서 메시지를 참조할 수 있도록 설정

                await view.wait() # 사용자의 선택을 기다림

                if view.selected_entry:
                    selected_info = view.selected_entry
                else:
                    # 시간 초과 또는 선택 없음
                    await ctx.followup.send("곡 선택이 취소되었습니다.")
                    return
            else:
                # 단일 URL이거나 검색 결과가 하나일 경우
                selected_info = info

            title = selected_info.get('title', 'Unknown Title')
            webpage_url = selected_info.get('webpage_url', f"https://www.youtube.com/watch?v={selected_info.get('id')}")

            state.queue.append({'url': webpage_url, 'title': title, 'ctx': ctx, 'webpage_url': webpage_url, 'added_by': 'user', 'prefetched': False})
            await ctx.followup.send(f'큐에 추가됨: {title}')

            # 봇이 이미 재생 중이고, 방금 추가한 곡이 큐의 유일한 곡이라면 즉시 프리페치
            if state.is_playing and len(state.queue) == 1:
                logger.info(f"[play] Triggering pre-emptive prefetch for user's song: {title}")
                self.bot.loop.create_task(self._prefetch_next_song(ctx.guild.id))

            if not state.is_playing:
                logger.debug(f"[play] Calling _play_next from play command. Current state.is_playing: {state.is_playing}")
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

            ydl_opts = {'quiet': True, 'noplaylist': False, 'extract_flat': True, 'source_address': '0.0.0.0'}
            with youtube_dl.YoutubeDL(ydl_opts) as ydl:
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

            # 봇이 이미 재생 중이고, 큐에 방금 추가한 곡들만 있다면 즉시 첫 곡을 프리페치
            if state.is_playing and len(state.queue) == added_count:
                 logger.info(f"[playlist] Triggering pre-emptive prefetch for the first song.")
                 self.bot.loop.create_task(self._prefetch_next_song(ctx.guild.id))
            
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

    @discord.slash_command(description="반복 모드를 설정합니다. (off, current, queue)")
    async def loop(self, ctx, mode: str):
        state = self._get_state(ctx.guild.id)
        mode = mode.lower()
        if mode not in ["off", "current", "queue"]:
            await ctx.respond("사용법: /loop off, /loop current, 또는 /loop queue", ephemeral=True)
            return
        
        state.loop_mode = mode
        await ctx.respond(f"반복 모드가 '{mode}'(으)로 설정되었습니다.")

    @discord.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        # 봇 자신이거나, 채널 변경이 없는 경우는 무시
        if member.id == self.bot.user.id or before.channel == after.channel:
            return

        # 봇이 음성 채널에 연결되어 있고, 이전 채널에 사람이 없게 된 경우
        if before.channel and self.bot.user in before.channel.members:
            # 봇 외에 다른 사람이 없는지 확인
            human_members_in_before = [m for m in before.channel.members if not m.bot]
            if not human_members_in_before:
                guild_id = before.channel.guild.id
                await self._check_and_leave(guild_id)

    def setup(bot):
        bot.add_cog(MusicCog(bot))