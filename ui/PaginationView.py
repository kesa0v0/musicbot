
import math  # cogs/music.py 상단 import 목록에 추가해주세요.
import discord

class PaginationView(discord.ui.View):
    """
    대기열 페이지네이션을 위한 View 클래스
    """
    def __init__(self, data, original_author, items_per_page=10):
        super().__init__(timeout=180)  # 180초 뒤 타임아웃
        self.data = data
        self.original_author = original_author
        self.items_per_page = items_per_page
        self.current_page = 1
        # 총 페이지 계산
        self.total_pages = math.ceil(len(self.data) / self.items_per_page)
        # 데이터가 없을 경우 1페이지로 고정
        if self.total_pages == 0:
            self.total_pages = 1
        
        self.message = None  # View가 전송된 메시지를 참조할 수 있도록

    def create_embed(self):
        """현재 페이지에 맞는 임베드를 생성합니다."""
        
        # 현재 페이지의 시작과 끝 인덱스 계산
        start_index = (self.current_page - 1) * self.items_per_page
        end_index = min(start_index + self.items_per_page, len(self.data))
        
        # 현재 페이지에 해당하는 데이터 슬라이스
        page_data = self.data[start_index:end_index]

        embed = discord.Embed(title="🎵 재생 대기열", color=discord.Color.blue())

        if not self.data:
            embed.description = "큐가 비어있습니다."
            embed.set_footer(text="페이지 1 / 1 (총 0곡)")
        else:
            # 임베드 설명란에 곡 목록 추가
            description_lines = []
            for i, item in enumerate(page_data, start=start_index + 1):
                title = item.get('title', 'Unknown Title')
                line = f"`{i}.` {title}"
                if item.get('added_by') == 'autoplay':
                    line += " (추천)"
                description_lines.append(line)
            
            embed.description = "\n".join(description_lines)
            embed.set_footer(text=f"페이지 {self.current_page} / {self.total_pages} (총 {len(self.data)}곡)")

        # 버튼 상태 업데이트 (첫 페이지/마지막 페이지일 때 비활성화)
        self.update_buttons()
        return embed

    def update_buttons(self):
        """버튼의 활성화/비활성화 상태를 업데이트합니다."""
        # '이전' 버튼: 1페이지일 때 비활성화
        self.prev_button.disabled = self.current_page == 1
        # '다음' 버튼: 마지막 페이지일 때 비활성화
        self.next_button.disabled = self.current_page == self.total_pages

    async def check_interaction(self, interaction: discord.Interaction) -> bool:
        """이 상호작용이 원래 명령어를 실행한 사용자의 것인지 확인합니다."""
        if interaction.user != self.original_author:
            await interaction.response.send_message("이 버튼은 당신을 위한 것이 아닙니다.", ephemeral=True)
            return False
        return True

    # --- 버튼 콜백 ---

    @discord.ui.button(label="< 이전", style=discord.ButtonStyle.secondary, custom_id="prev_page")
    async def prev_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        if not await self.check_interaction(interaction):
            return

        if self.current_page > 1:
            self.current_page -= 1
            embed = self.create_embed()
            await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="다음 >", style=discord.ButtonStyle.secondary, custom_id="next_page")
    async def next_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        if not await self.check_interaction(interaction):
            return

        if self.current_page < self.total_pages:
            self.current_page += 1
            embed = self.create_embed()
            await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="닫기 ❌", style=discord.ButtonStyle.danger, custom_id="stop_pagination")
    async def stop_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        if not await self.check_interaction(interaction):
            return
        
        # 모든 버튼 비활성화
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)
        self.stop()

    async def on_timeout(self):
        try:
            if self.message:
                # 타임아웃 시 모든 버튼 비활성화
                for item in self.children:
                    item.disabled = True
                await self.message.edit(view=self)
        except discord.NotFound:
            pass  # 메시지가 이미 삭제된 경우
        finally:
            self.stop()