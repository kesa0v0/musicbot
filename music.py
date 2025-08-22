import discord
import asyncio
import yt_dlp as youtube_dl
import functools
from collections import deque
from utils import get_related_videos
import logging
import random
import discord.ui
import re

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
        self.play_lock = asyncio.Lock() # 재생 로직 접근을 제어할 Lock

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
        if self.message:
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

    def _get_state(self, guild_id) -> GuildState:
        """해당 길드의 상태 객체를 가져오거나 새로 생성합니다."""
        if guild_id not in self.states:
            self.states[guild_id] = GuildState(self.bot.loop)
        return self.states[guild_id]

    async def _prepare_song(self, song: dict) -> bool:
        """
        노래 딕셔너리를 받아 스트림 URL을 추출하고 딕셔너리를 직접 업데이트합니다.
        성공 시 True, 실패 시 False를 반환합니다.
        """
        if song.get('prepared', False):
            return True

        logger.info(f"[prepare_song] Starting for: {song['title']}")
        try:
            with youtube_dl.YoutubeDL(YDL_OPTS) as ydl:
                info = await self.bot.loop.run_in_executor(None, functools.partial(ydl.extract_info, song['webpage_url'], download=False))
            
            audio_formats = sorted([f for f in info['formats'] if f.get('acodec') != 'none' and f.get('url')], key=lambda x: 0 if x.get('abr') is None else x.get('abr'), reverse=True)

            if audio_formats:
                song['stream_url'] = audio_formats[0]['url']
                song['prepared'] = True
                logger.info(f"[prepare_song] Success for: {song['title']}")
                return True
            else:
                logger.error(f"[prepare_song] No suitable audio stream found for: {song['title']}")
                song['prepared'] = False
                return False
        except Exception as e:
            logger.error(f"[prepare_song] Failed for {song['title']}: {e}")
            song['prepared'] = False
            return False

    async def _add_autoplay_song(self, state: GuildState, ctx):
        """큐가 비었을 때 자동재생 곡을 찾아 큐에 추가합니다."""
        if not state.autoplay_enabled or not state.current_song:
            return

        logger.info(f"[autoplay] Triggered. Finding recommendation based on: {state.current_song['title']}")
        last_url = state.current_song['webpage_url']
        match = re.search(r"v=([\w-]+)", last_url)
        video_id = match.group(1) if match else None

        if not video_id:
            return

        try:
            related_videos = await self.bot.loop.run_in_executor(
                None, functools.partial(get_related_videos, video_id, max_results=10)
            )
            if not related_videos:
                return

            current_queue_ids = {re.search(r"v=([\w-]+)", s['webpage_url']).group(1) for s in state.queue if re.search(r"v=([\w-]+)", s['webpage_url'])}
            played_history_ids = set(state.played_history)
            
            filtered_videos = [
                v for v in related_videos 
                if v.get('id') and v['id'] not in current_queue_ids and v['id'] not in played_history_ids
            ]

            if filtered_videos:
                video_info = random.choice(filtered_videos)
                video_id = video_info.get('id')
                title = video_info.get('title', 'Unknown Title')
                url = f"https://www.youtube.com/watch?v={video_id}"
                
                state.queue.append({'webpage_url': url, 'title': title, 'ctx': ctx, 'added_by': 'autoplay', 'prepared': False})
                logger.info(f"[autoplay] Added '{title}' to queue.")

        except Exception as e:
            logger.error(f"[autoplay] Failed to add song: {e}")

    async def _play_next(self, ctx):
        """재생 로직의 중심. 큐의 다음 곡을 재생하고, 없으면 자동재생을 시도합니다."""
        state = self._get_state(ctx.guild.id)
        
        async with state.play_lock: # Lock을 사용하여 동시 접근 방지
            voice_client = ctx.voice_client

            if not voice_client or not voice_client.is_connected():
                state.is_playing = False
                return

            # 1. 다음 곡 가져오기 (큐가 비었으면 자동재생 시도)
            if not state.queue:
                await self._add_autoplay_song(state, ctx)
                if not state.queue: # 자동재생으로도 추가 못했으면 종료
                    logger.info(f"[_play_next] Stopping playback as queue is empty.")
                    state.is_playing = False
                    state.current_song = None
                    return

            next_song = state.queue.popleft()

            # 2. 스트림 URL 준비 (Just-in-Time)
            if not next_song.get('prepared', False):
                logger.info(f"[_play_next] Song not prepared. Preparing now: {next_song['title']}")
                if not await self._prepare_song(next_song):
                    await ctx.channel.send(f"'{next_song['title']}'을(를) 재생할 수 없어 건너뜁니다.")
                    # Lock을 해제하기 전에 다음 호출을 예약해야 함
                    self.bot.loop.create_task(self._play_next(ctx))
                    return
            
            play_url = next_song['stream_url']
            state.is_playing = True
            state.current_song = next_song

            # 3. 재생 후 실행될 콜백 함수 정의
            def after_playing(error):
                if error:
                    logger.error(f"[_play_next:after] Playback error for {next_song['title']}: {error}")
                
                match = re.search(r"v=([\w-]+)", next_song['webpage_url'])
                if match:
                    state.played_history.append(match.group(1))

                if state.loop_mode == "current":
                    state.queue.appendleft(next_song)
                elif state.loop_mode == "queue":
                    state.queue.append(next_song)

                self.bot.loop.create_task(self._play_next(ctx))

            # 4. 재생 시작
            try:
                source = discord.FFmpegPCMAudio(play_url, **FFMPEG_OPTS)
                voice_client.play(source, after=after_playing)
                await ctx.channel.send(f'Now playing: {next_song["title"]} 
URL: <{next_song["webpage_url"]}>
')

                # 5. 다음 곡 미리 준비 (Hybrid Prefetch)
                if state.queue:
                    self.bot.loop.create_task(self._prepare_song(state.queue[0]))

            except Exception as e:
                logger.error(f"[_play_next] Critical error for {next_song['title']}: {e}")
                await ctx.channel.send(f"'{next_song['title']}' 재생 중 심각한 오류가 발생했습니다.")
                self.bot.loop.create_task(self._play_next(ctx))

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
            "/loop [off/current/queue] : 반복 모드 설정\n"
        )
        await ctx.respond(help_text, ephemeral=True)

    @discord.slash_command(description="노래를 재생하거나 큐에 추가합니다.")
    async def play(self, ctx, query: str):
        logger.info(f"[play] Received query: {query}")
        await ctx.defer()
        state = self._get_state(ctx.guild.id)

        if any(song.get('added_by') == 'autoplay' for song in state.queue):
            state.queue = deque(song for song in state.queue if song.get('added_by') != 'autoplay')
            logger.info(f"[play] User interrupted autoplay. Clearing autoplay songs.")
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

            search_query = f"ytsearch5:{query}" if not query.startswith('http') else query
            
            ydl_opts = {'quiet': True, 'noplaylist': True, 'default_search': 'ytsearch', 'source_address': '0.0.0.0'}
            with youtube_dl.YoutubeDL(ydl_opts) as ydl:
                info = await self.bot.loop.run_in_executor(None, functools.partial(ydl.extract_info, search_query, download=False))
            
            if 'entries' in info:
                entries = [e for e in info['entries'] if e and e.get('id')][:5]
                if not entries:
                    await ctx.followup.send(f"'{query}'에 대한 검색 결과를 찾을 수 없습니다.")
                    return

                msg = "다음 중 재생할 곡을 선택해주세요:\n" + '\n'.join([f"{i+1}. {e.get('title', 'Unknown')}" for i, e in enumerate(entries)])
                view = SongSelectionView(entries, ctx)
                message = await ctx.followup.send(msg, view=view)
                view.message = message
                await view.wait()

                selected_info = view.selected_entry
                if not selected_info:
                    return
            else:
                selected_info = info

            title = selected_info.get('title', 'Unknown Title')
            webpage_url = selected_info.get('webpage_url', f"https://www.youtube.com/watch?v={selected_info.get('id')}")

            state.queue.append({'webpage_url': webpage_url, 'title': title, 'ctx': ctx, 'added_by': 'user', 'prepared': False})
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
                if not entry or not entry.get('id'): continue
                if len(state.queue) >= QUEUE_LIMIT: break
                
                title = entry.get('title', 'Unknown Title')
                webpage_url = f"https://www.youtube.com/watch?v={entry['id']}"
                state.queue.append({'webpage_url': webpage_url, 'title': title, 'ctx': ctx, 'added_by': 'user', 'prepared': False})
                added_count += 1

            await ctx.followup.send(f'{added_count}개의 노래를 큐에 추가했습니다.')
            
            if not state.is_playing and added_count > 0:
                await self._play_next(ctx)
        except Exception as e:
            logger.error(f"플레이리스트 로딩 중 오류: {e}")
            await ctx.followup.send(f'플레이리스트를 가져오는 중 오류가 발생했습니다: {e}')

    @discord.slash_command(description="현재 재생 중인 노래를 건너뜁니다.")
    async def skip(self, ctx):
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.stop()
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

        msg_lines = [f'**현재 대기열:**']
        for i, item in enumerate(state.queue, 1):
            line = f'{i}. {item["title"]}'
            if item.get('added_by') == 'autoplay':
                line += " (추천)"
            msg_lines.append(line)
            if i >= 15:
                msg_lines.append(f"... 외 {len(state.queue) - 15}곡")
                break
        
        await ctx.respond('\n'.join(msg_lines))

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
            await ctx.respond(f'현재 재생 중: {state.current_song["title"]} 
URL: <{state.current_song["webpage_url"]}>
')
        else:
            await ctx.respond("재생 중인 노래가 없습니다.", ephemeral=True)

    @discord.slash_command(description="음성 채널에서 나갑니다.")
    async def leave(self, ctx):
        state = self._get_state(ctx.guild.id)
        if ctx.voice_client:
            await ctx.voice_client.disconnect()
            state.is_playing = False
            state.current_song = None
            if ctx.guild.id in self.states:
                del self.states[ctx.guild.id]
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
        if member.id == self.bot.user.id or before.channel == after.channel:
            return

        voice_client = member.guild.voice_client
        if voice_client and voice_client.is_connected():
            if len(voice_client.channel.members) == 1:
                logger.info(f"[auto-leave] Leaving voice channel in guild {member.guild.id} due to inactivity.")
                state = self._get_state(member.guild.id)
                state.is_playing = False
                state.current_song = None
                await voice_client.disconnect()
                if member.guild.id in self.states:
                    del self.states[member.guild.id]

def setup(bot):
    bot.add_cog(MusicCog(bot))