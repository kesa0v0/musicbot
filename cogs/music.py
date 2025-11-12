from cogs import PaginationView
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
    'cookiefile': './cookies.txt',
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
        self.message = None

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
        try:
            for item in self.children:
                item.disabled = True
            if self.message:
                await self.message.edit(content="곡 선택 시간이 초과되었습니다.", view=self)
        except discord.NotFound:
            pass # 메시지가 이미 삭제된 경우
        except Exception as e:
            logger.error(f"[view_timeout] Error disabling view: {e}")
        finally:
            self.stop()

    def create_callback(self, entry):
        async def callback(interaction: discord.Interaction):
            try:
                if interaction.user != self.original_ctx.author:
                    await interaction.response.send_message("이 버튼은 당신을 위한 것이 아닙니다.", ephemeral=True)
                    return
                self.selected_entry = entry
                for item in self.children:
                    item.disabled = True
                await interaction.response.edit_message(content=f"'{entry.get('title', 'Unknown Title')}'을(를) 선택했습니다.", view=self)
            except Exception as e:
                logger.error(f"[view_callback] Error in selection callback: {e}")
            finally:
                self.stop()
        return callback

    async def cancel_callback(self, interaction: discord.Interaction):
        try:
            if interaction.user != self.original_ctx.author:
                await interaction.response.send_message("이 버튼은 당신을 위한 것이 아닙니다.", ephemeral=True)
                return
            self.selected_entry = None # 선택 취소
            for item in self.children:
                item.disabled = True
            await interaction.response.edit_message(content="곡 선택이 취소되었습니다.", view=self)
        except Exception as e:
            logger.error(f"[view_cancel] Error in cancel callback: {e}")
        finally:
            self.stop()

class MusicCog(discord.Cog):
    """음악 기능 관련 모든 로직을 담는 Cog 클래스"""
    def __init__(self, bot):
        self.bot = bot
        self.states = {} # {guild_id: GuildState}

    async def cog_before_invoke(self, ctx: discord.ApplicationContext):
        """모든 슬래시 커맨드 실행 전에 호출되는 후크 함수. 명령어 사용을 로깅합니다."""
        logger.info(
            f"[COMMAND] User='{ctx.author}' Guild='{ctx.guild.name}' "
            f"Command='/{ctx.command.name}' Options={ctx.options}"
        )

    async def cog_command_error(self, ctx: discord.ApplicationContext, error: Exception):
        """명령어 실행 중 발생한 예외를 전역적으로 처리하는 핸들러."""
        # 원본 에러가 discord.ApplicationCommandInvokeError인 경우, 실제 원인 에러를 추출합니다.
        if isinstance(error, discord.ApplicationCommandInvokeError):
            error = error.original

        logger.error(f"[GLOBAL_ERROR] Guild='{ctx.guild.name}' Command='/{ctx.command.name}' Error: {error}", exc_info=True)
        try:
            # 이미 응답(defer 포함)이 보내졌는지 확인합니다.
            if not ctx.response.is_done():
                await ctx.respond("명령어 실행 중 알 수 없는 오류가 발생했습니다. 개발자에게 문의해주세요.", ephemeral=True)
            else:
                await ctx.followup.send("명령어 실행 중 알 수 없는 오류가 발생했습니다. 개발자에게 문의해주세요.", ephemeral=True)
        except (discord.Forbidden, discord.NotFound):
            logger.warning(f"[GLOBAL_ERROR] Could not send error message to Guild='{ctx.guild.name}'.")
            pass # 오류 메시지 전송조차 실패한 경우

    def _get_state(self, guild_id) -> GuildState:
        """해당 길드의 상태 객체를 가져오거나 새로 생성합니다."""
        if guild_id not in self.states:
            self.states[guild_id] = GuildState(self.bot.loop)
        return self.states[guild_id]

    async def _prepare_song(self, song: dict) -> bool:
        if song.get('prepared', False):
            return True
        logger.info(f"[prepare_song] Starting for: {song['title']}")
        try:
            with youtube_dl.YoutubeDL(YDL_OPTS) as ydl:
                info = await self.bot.loop.run_in_executor(None, functools.partial(ydl.extract_info, song['webpage_url'], download=False))
            filtered_formats = [f for f in info.get('formats', []) if f.get('acodec') != 'none' and f.get('url') and 'hls' not in f.get('protocol', '')]
            if not filtered_formats:
                logger.error(f"[prepare_song] No suitable non-HLS audio stream found for: {song['title']}")
                song['prepared'] = False
                return False
            filtered_formats.sort(key=lambda f: f.get('abr') or 0, reverse=True)
            song['stream_url'] = filtered_formats[0]['url']
            song['prepared'] = True
            logger.info(f"[prepare_song] Success for: {song['title']} (Format: {filtered_formats[0].get('format_id')})")
            return True
        except Exception as e:
            logger.error(f"[prepare_song] Failed for {song['title']}: {e}")
            song['prepared'] = False
            return False

    async def _add_autoplay_song(self, state: GuildState, ctx):
        if not state.autoplay_enabled or not state.current_song: return
        logger.info(f"[autoplay] Triggered. Finding recommendation based on: {state.current_song['title']}")
        match = re.search(r"v=([\w-]+)", state.current_song['webpage_url'])
        if not match: return
        video_id = match.group(1)
        try:
            related_videos = await self.bot.loop.run_in_executor(None, functools.partial(get_related_videos, video_id, max_results=10))
            if not related_videos: return
            current_queue_ids = {re.search(r"v=([\w-]+)", s['webpage_url']).group(1) for s in state.queue if re.search(r"v=([\w-]+)", s['webpage_url'])}
            played_history_ids = set(state.played_history)
            filtered_videos = [v for v in related_videos if v.get('id') and v['id'] not in current_queue_ids and v['id'] not in played_history_ids]
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
        state = self._get_state(ctx.guild.id)
        async with state.play_lock:
            voice_client = ctx.voice_client
            if not voice_client or not voice_client.is_connected():
                state.is_playing = False
                return
            if not state.queue:
                await self._add_autoplay_song(state, ctx)
                if not state.queue:
                    logger.info(f"[_play_next] Stopping playback as queue is empty.")
                    state.is_playing = False
                    state.current_song = None
                    return
            next_song = state.queue.popleft()
            if not next_song.get('prepared', False):
                logger.info(f"[_play_next] Song not prepared. Preparing now: {next_song['title']}")
                if not await self._prepare_song(next_song):
                    try:
                        await ctx.channel.send(f"'{next_song['title']}'을(를) 재생할 수 없어 건너뜁니다.")
                    except (discord.Forbidden, discord.NotFound): pass
                    self.bot.loop.create_task(self._play_next(ctx))
                    return
            play_url = next_song['stream_url']
            state.is_playing = True
            state.current_song = next_song
            def after_playing(error):
                if error: logger.error(f"[_play_next:after] Playback error for {next_song['title']}: {error}")
                match = re.search(r"v=([\w-]+)", next_song['webpage_url'])
                if match: state.played_history.append(match.group(1))
                if state.loop_mode == "current": state.queue.appendleft(next_song)
                elif state.loop_mode == "queue": state.queue.append(next_song)
                self.bot.loop.create_task(self._play_next(ctx))
            try:
                source = discord.FFmpegPCMAudio(play_url, **FFMPEG_OPTS)
                voice_client.play(source, after=after_playing)
                try:
                    await ctx.channel.send(f'Now playing: {next_song["title"]}\nURL: <{next_song["webpage_url"]}>')
                except (discord.Forbidden, discord.NotFound): pass
                if state.queue: self.bot.loop.create_task(self._prepare_song(state.queue[0]))
                elif state.autoplay_enabled: self.bot.loop.create_task(self._add_autoplay_song(state, ctx))
            except Exception as e:
                logger.error(f"[_play_next] Critical error for {next_song['title']}: {e}")
                try:
                    await ctx.channel.send(f"'{next_song['title']}' 재생 중 심각한 오류가 발생했습니다.")
                except (discord.Forbidden, discord.NotFound): pass
                self.bot.loop.create_task(self._play_next(ctx))

    @discord.slash_command(description="노래를 재생하거나 큐에 추가합니다.")
    async def play(self, ctx, query: str):
        await ctx.defer()
        state = self._get_state(ctx.guild.id)
        if any(song.get('added_by') == 'autoplay' for song in state.queue):
            state.queue = deque(song for song in state.queue if song.get('added_by') != 'autoplay')
            logger.info(f"[play] User interrupted autoplay. Clearing autoplay songs.")
            try:
                await ctx.channel.send("자동재생 목록을 지웠습니다. 요청하신 곡을 우선 재생합니다.", delete_after=10)
            except (discord.Forbidden, discord.NotFound): pass
        if len(state.queue) >= QUEUE_LIMIT:
            await ctx.followup.send(f'큐가 가득 찼습니다! (최대 {QUEUE_LIMIT}곡)')
            return
        voice_client = ctx.voice_client
        # Check if the bot is in a voice channel and if it's connected.
        if voice_client and voice_client.is_connected():
            # If the user is in a different channel, move the bot.
            if ctx.author.voice and ctx.author.voice.channel != voice_client.channel:
                logger.info(f"Moving to user's channel: {ctx.author.voice.channel.name}")
                await voice_client.move_to(ctx.author.voice.channel)
        else:
            # The bot is not connected to any voice channel in this guild.
            if ctx.author.voice:
                # If there's a lingering, broken client, disconnect it first.
                if voice_client:
                    logger.warning(f"Found a lingering, disconnected voice client in {ctx.guild.name}. Cleaning up.")
                    try:
                        await voice_client.disconnect(force=True)
                    except Exception as e:
                        logger.error(f"Error force-disconnecting lingering client: {e}")

                # Now, connect to the user's channel.
                try:
                    logger.info(f"Connecting to voice channel: {ctx.author.voice.channel.name}")
                    await ctx.author.voice.channel.connect(timeout=15.0)
                except (discord.errors.ConnectionClosed, asyncio.TimeoutError) as e:
                    logger.error(f"[voice_connect] Known error connecting to voice in {ctx.guild.name}: {e}")
                    await ctx.followup.send("음성 채널 연결에 실패했습니다. Discord 서버 상태에 문제가 있을 수 있습니다. 잠시 후 다시 시도해주세요.")
                    if ctx.guild.id in self.states:
                        del self.states[ctx.guild.id]
                    return
                except Exception as e:
                    # This will be caught by the global error handler, but logging it here gives more context.
                    logger.error(f"[voice_connect] Unexpected error connecting to voice in {ctx.guild.name}: {e}", exc_info=True)
                    # Re-raise to be caught by the global handler, which will notify the user.
                    raise e
            else:
                await ctx.followup.send("음성 채널에 먼저 참여해주세요.")
                return
        search_query = f"ytsearch5:{query}" if not query.startswith('http') else query
        with youtube_dl.YoutubeDL(YDL_OPTS) as ydl:
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
            if not selected_info: return
        else:
            selected_info = info
        title = selected_info.get('title', 'Unknown Title')
        webpage_url = selected_info.get('webpage_url', f"https://www.youtube.com/watch?v={selected_info.get('id')}")
        state.queue.append({'webpage_url': webpage_url, 'title': title, 'ctx': ctx, 'added_by': 'user', 'prepared': False})
        await ctx.followup.send(f'큐에 추가됨: {title}')
        if not state.is_playing:
            await self._play_next(ctx)

    @discord.slash_command(description="유튜브 플레이리스트를 큐에 추가합니다.")
    async def playlist(self, ctx, url: str):
        await ctx.defer()
        state = self._get_state(ctx.guild.id)
        if any(song.get('added_by') == 'autoplay' for song in state.queue):
            state.queue = deque(song for song in state.queue if song.get('added_by') != 'autoplay')
            try:
                await ctx.channel.send("자동재생 목록을 지웠습니다. 요청하신 재생목록을 우선 추가합니다.", delete_after=10)
            except (discord.Forbidden, discord.NotFound): pass
        voice_client = ctx.voice_client
        # Check if the bot is in a voice channel and if it's connected.
        if voice_client and voice_client.is_connected():
            # If the user is in a different channel, move the bot.
            if ctx.author.voice and ctx.author.voice.channel != voice_client.channel:
                logger.info(f"Moving to user's channel: {ctx.author.voice.channel.name}")
                await voice_client.move_to(ctx.author.voice.channel)
        else:
            # The bot is not connected to any voice channel in this guild.
            if ctx.author.voice:
                # If there's a lingering, broken client, disconnect it first.
                if voice_client:
                    logger.warning(f"Found a lingering, disconnected voice client in {ctx.guild.name}. Cleaning up.")
                    try:
                        await voice_client.disconnect(force=True)
                    except Exception as e:
                        logger.error(f"Error force-disconnecting lingering client: {e}")

                # Now, connect to the user's channel.
                try:
                    logger.info(f"Connecting to voice channel: {ctx.author.voice.channel.name}")
                    await ctx.author.voice.channel.connect(timeout=15.0)
                except (discord.errors.ConnectionClosed, asyncio.TimeoutError) as e:
                    logger.error(f"[voice_connect] Known error connecting to voice in {ctx.guild.name}: {e}")
                    await ctx.followup.send("음성 채널 연결에 실패했습니다. Discord 서버 상태에 문제가 있을 수 있습니다. 잠시 후 다시 시도해주세요.")
                    if ctx.guild.id in self.states:
                        del self.states[ctx.guild.id]
                    return
                except Exception as e:
                    # This will be caught by the global error handler, but logging it here gives more context.
                    logger.error(f"[voice_connect] Unexpected error connecting to voice in {ctx.guild.name}: {e}", exc_info=True)
                    # Re-raise to be caught by the global handler, which will notify the user.
                    raise e
            else:
                await ctx.followup.send("음성 채널에 먼저 참여해주세요.")
                return
        with youtube_dl.YoutubeDL({'quiet': True, 'noplaylist': False, 'extract_flat': True, 'source_address': '0.0.0.0', 'cookiefile': './cookies.txt',}) as ydl:
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
        # View에 데이터를 넘겨주기 위해 deque를 list로 변환
        queue_list = list(state.queue)

        # 페이지네이션 View 인스턴스 생성
        # (한 페이지에 10개씩, 원본 명령어 사용자만 조작 가능)
        view = PaginationView(data=queue_list, original_author=ctx.author, items_per_page=10)
        
        # 첫 페이지의 임베드 생성
        initial_embed = view.create_embed()

        # 메시지를 전송하고, 전송된 메시지 객체를 view에 저장 (타임아웃 시 편집 위함)
        await ctx.respond(embed=initial_embed, view=view)
        view.message = await ctx.original_response()

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
            await ctx.respond(f'현재 재생 중: {state.current_song["title"]}\nURL: <{state.current_song["webpage_url"]}>')
        else:
            await ctx.respond("재생 중인 노래가 없습니다.", ephemeral=True)

    @discord.slash_command(description="음성 채널에서 나갑니다.")
    async def leave(self, ctx):
        state = self._get_state(ctx.guild.id)
        voice_client = ctx.voice_client
        
        if voice_client and voice_client.is_connected():
            try:
                await voice_client.disconnect()
                await ctx.respond("음성 채널을 나갔습니다.")
            except Exception as e:
                logger.error(f"[voice_disconnect] Error disconnecting from voice channel in {ctx.guild.name}: {e}")
                await ctx.respond("음성 채널을 나가는 중 오류가 발생했습니다. 상태를 초기화합니다.", ephemeral=True)
            finally:
                state.is_playing = False
                state.current_song = None
                if ctx.guild.id in self.states:
                    del self.states[ctx.guild.id]
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
            # 채널에 봇만 남았는지 확인
            if len(voice_client.channel.members) == 1:
                logger.info(f"[auto-leave] Leaving voice channel in guild {member.guild.id} due to inactivity.")
                state = self._get_state(member.guild.id)
                try:
                    await voice_client.disconnect()
                except Exception as e:
                    logger.error(f"[auto-leave] Error disconnecting from voice channel in {member.guild.name}: {e}")
                finally:
                    state.is_playing = False
                    state.current_song = None
                    if member.guild.id in self.states:
                        del self.states[member.guild.id]

def setup(bot):
    bot.add_cog(MusicCog(bot))