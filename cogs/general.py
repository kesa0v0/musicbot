import discord
from discord.ext import commands

# 자동 완성 핸들러는 self를 인자로 받지 않는 독립 함수여야 합니다.
async def get_command_categories(ctx: discord.AutocompleteContext):
    """/help 명령어의 category 옵션에 대한 자동완성 목록을 생성합니다."""
    # 숨기고 싶은 Cog가 있다면 여기에 이름을 추가하세요.
    hidden_cogs = [] 
    # ctx.bot을 통해 현재 봇의 Cog 목록에 접근합니다.
    return [cog for cog in ctx.bot.cogs.keys() if cog not in hidden_cogs]


class GeneralCog(commands.Cog):
    """봇의 일반적인 명령어를 포함하는 Cog입니다."""
    def __init__(self, bot):
        self.bot = bot

    @commands.slash_command(
        name="help",
        description="봇의 명령어 도움말을 보여줍니다."
    )
    async def help_command(
        self,
        ctx: discord.ApplicationContext,
        category: str | None = discord.Option(
            name="category",
            description="자세한 도움말을 보고 싶은 카테고리를 선택하세요.",
            autocomplete=discord.utils.basic_autocomplete(get_command_categories),
            required=False,
            default=None
        )
    ):
        """하나의 명령어로 전체 도움말과 카테고리별 도움말을 모두 처리합니다."""
        
        # 1. 카테고리(Cog)가 지정되지 않은 경우
        if not category:
            embed = discord.Embed(
                title="도움말",
                description=f"안녕하세요! `{self.bot.user.name}` 봇입니다.\n" 
                            f"아래 카테고리 중 하나를 선택하여 `/help [카테고리]`를 입력하시면 자세한 명령어 목록을 볼 수 있습니다.",
                color=discord.Color.blue()
            )
            
            for cog_name, cog in self.bot.cogs.items():
                if cog_name in getattr(self, 'hidden_cogs', []):
                    continue
                
                docstring = cog.__doc__ or "설명이 없습니다."
                embed.add_field(name=f"**{cog_name}**", value=docstring, inline=False)
            
            await ctx.respond(embed=embed)
            return

        # 2. 카테고리(Cog)가 지정된 경우
        target_cog = self.bot.get_cog(category)
        if not target_cog:
            await ctx.respond(f"'{category}'라는 이름의 카테고리를 찾을 수 없습니다.", ephemeral=True)
            return

        embed = discord.Embed(
            title=f"📚 {target_cog.qualified_name} 명령어 목록",
            description=target_cog.__doc__ or "",
            color=discord.Color.green()
        )

        # 봇의 전체 명령어 목록에서 현재 Cog에 해당하는 명령어만 필터링
        commands_list = [cmd for cmd in self.bot.application_commands if cmd.cog == target_cog]
        for cmd in commands_list:
            params_list = []
            for option in cmd.options:
                if option.required:
                    params_list.append(f"<{option.name}>")
                else:
                    params_list.append(f"[{option.name}]")
            
            params_str = " ".join(params_list)
            
            field_name = f"`/{cmd.name} {params_str}`".strip()
            field_value = cmd.description or "설명이 없습니다."
            embed.add_field(name=field_name, value=field_value, inline=False)
        
        embed.set_footer(text="<>는 필수 입력, []는 선택 입력 항목을 의미합니다.")
        await ctx.respond(embed=embed)


def setup(bot):
    """Cog를 봇에 등록합니다."""
    bot.add_cog(GeneralCog(bot))