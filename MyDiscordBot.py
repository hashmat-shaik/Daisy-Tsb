import io
import re
import os
import discord
import json
import random
from datetime import datetime, timedelta, timezone, time
from threading import Thread
import asyncio
import sqlite3
import aiohttp
from flask import Flask
from discord.ext import commands, tasks
from discord import app_commands

# Import your custom modules

from lb_image_gen import draw_leaderboard, draw_streak_leaderboard
from repDataBase import setupRepDB, add_rep
from fun_replies import check_humor
from tasksDataBase import setupTaskDB, getUserData, SaveUserTasks
from excludedChannels import setupExChannelDB, getExChannel, addChannel
from tagsDataBase import (setupTagsDB, getUserTags, addUserTag, removeUserTag,
                          MAX_TAGS, MAX_TAG_LENGTH,
                          getActiveTag, setActiveTag, clearActiveTag)
from timeDataBase import (setupTimeDB, getUserTime, SaveUserTime, get_leaderboard_data,
                          get_streak_leaderboard, getUserDailyTime, get_streak_info,
                          get_contextual_data, setupTagTimeDB, SaveUserTimeByTag, getUserTagTimes,
                          setupDailyHistoryDB, snapshotDailyTime, get_last_7_days,
                          get_weekly_leaderboard, get_weekly_rank)
from daily_report_gen import generate_stats_image

# Bot setup
bot = commands.Bot(command_prefix="!", intents=discord.Intents.all())
bot.report_channel_id = None

SESSION_FILE = "active_sessions.json"

# Session management functions
def load_voice_sessions():
    if not os.path.exists(SESSION_FILE):
        return {}
    try:
        with open(SESSION_FILE, "r") as f:
            data = json.load(f)
            return {int(uid): datetime.fromisoformat(ts) for uid, ts in data.items()}
    except Exception as e:
        print(f"Error loading sessions: {e}")
        return {}

def save_voice_sessions(sessions):
    try:
        data = {str(uid): ts.isoformat() for uid, ts in sessions.items()}
        with open(SESSION_FILE, "w") as f:
            json.dump(data, f)
    except Exception as e:
        print(f"Error saving sessions: {e}")

voiceTrack = load_voice_sessions()

# ==========================================
#  REPORTING SYSTEM
# ==========================================
@bot.tree.command(name="set_report_channel", description="MODS ONLY: Set the channel for forwarded reports")
@app_commands.checks.has_permissions(manage_channels=True)
async def set_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    bot.report_channel_id = channel.id
    await interaction.response.send_message(f"Reports will now be sent to {channel.mention}", ephemeral=True)

async def report_context_menu(interaction: discord.Interaction, message: discord.Message):
    target_channel = bot.get_channel(bot.report_channel_id)
    if not target_channel:
        return await interaction.response.send_message("Staff needs to setup report channel. Please contact any Staff member for help.", ephemeral=True)

    safe_content = message.content.replace('\n', ' ')[:1024]
    
    embed = discord.Embed(
        title="**Report**",
        color=discord.Color.dark_gold(),
        timestamp=interaction.created_at
    )
    
    embed.add_field(
        name="Reported for", 
        value=f"{message.author.mention}\nID: `{message.author.id}`", 
        inline=True
    )
    
    embed.add_field(
        name="Reporter", 
        value=f"{interaction.user.mention}\nID: `{interaction.user.id}`", 
        inline=True
    )

    embed.add_field(name="Message", value=f'"{safe_content}"', inline=False)

    if message.reference and message.reference.resolved:
        original_msg = message.reference.resolved
        embed.add_field(
            name="Replying To", 
            value=f"{original_msg.author.mention}: \"{original_msg.content[:100]}\"\nID: `{original_msg.author.id}`", 
            inline=False
        )

    await target_channel.send(content="Attention Staff!", embed=embed)
    await interaction.response.send_message("Report sent to Staff. Take a sip of Coffee and get back to Work!", ephemeral=True)

report_menu = app_commands.ContextMenu(
    name="Report a User",
    callback=report_context_menu
)

# ==========================================
#  INVITE SYSTEM
# ==========================================
@bot.tree.command(name="invite_members", description="Send DMs to specific users mentioned in the command")
@app_commands.describe(
    mentions="Mention the users you want to invite (e.g. @User1 @User2)",
    custom_message="Optional message to include in the invite"
)
async def invite_mentions(
    interaction: discord.Interaction, 
    mentions: str,
    custom_message: str = None  
):
    await interaction.response.defer(ephemeral=True)

    user_ids = re.findall(r'<@!?(\d+)>', mentions)
    
    if not user_ids:
        return await interaction.followup.send("You didn't mention any valid users!", ephemeral=True)

    user_ids = list(set(user_ids))

    # Build dynamic invite message
    invite_text = f"join them in <#{interaction.channel_id}> "

    if custom_message:
        invite_text += f"\n\n💬 Message from {interaction.user.display_name} :** {custom_message}**"

    embed = discord.Embed(
        title="📬 You've been invited!",
        description=f"**{interaction.user.display_name}** has sent you an invitation from **{interaction.guild.name}**.",
        color=discord.Color.blue(),
        timestamp=interaction.created_at
    )

    if interaction.guild.icon:
        embed.set_thumbnail(url=interaction.guild.icon.url)

    embed.add_field(name="Action", value=invite_text)

    success_count = 0
    for u_id in user_ids:
        try:
            user = await bot.fetch_user(int(u_id))
            if user.bot:
                continue
            
            await user.send(embed=embed)
            success_count += 1
        except (discord.Forbidden, discord.NotFound, ValueError):
            continue

    await interaction.followup.send(
        f"Attempted to notify {len(user_ids)} users. Successfully delivered to {success_count}.",
        ephemeral=True
    )

# ==========================================
#  HELPER FUNCTIONS
# ==========================================
def level(userID):
    td = timedelta(seconds=int(getUserDailyTime(userID)))
    study_hours = td.total_seconds() / 3600
    if study_hours < 5:
        return ("Iron", 5, study_hours)
    elif study_hours < 10:
        return ("Bronze", 10, study_hours)
    elif study_hours < 15:
        return ("Silver", 15, study_hours)
    elif study_hours < 30:
        return ("Gold", 30, study_hours)
    elif study_hours < 50:
        return ("Platinum", 50, study_hours)
    elif study_hours < 75:
        return ("Diamond", 75, study_hours)
    elif study_hours < 110:
        return ("Master", 110, study_hours)
    elif study_hours < 150:
        return ("Grandmaster", 150, study_hours)
    elif study_hours < 200:
        return ("Immortal", 200, study_hours)
    elif study_hours < 300:
        return ("Conqueror", 300, study_hours)
    else:
        return ("God", 1000, study_hours)
def flush_active_voice_time():
    current_time = datetime.now(timezone.utc)

    for user_id, start_time in voiceTrack.items():
        duration = (current_time - start_time).total_seconds()

        if duration > 0:
            SaveUserTime(user_id, duration)

            tag = getActiveTag(user_id)
            if tag:
                SaveUserTimeByTag(user_id, tag, duration)

            voiceTrack[user_id] = current_time

    save_voice_sessions(voiceTrack)

def get_user_rank(userID, lbtype):
    connection = sqlite3.connect('userTimeUsage.db')
    cursor = connection.cursor()
    if lbtype == 'all time':
        cursor.execute('''
            SELECT COUNT(*) FROM userTime 
            WHERE time > (SELECT time FROM userTime WHERE userID = ?)
        ''', (userID,))
        users_ahead = cursor.fetchone()[0]
    
    if lbtype == 'daily':
        cursor.execute('''
            SELECT COUNT(*) FROM userTime 
            WHERE daily_time > (SELECT daily_time FROM userTime WHERE userID = ?)
        ''', (userID,))
        users_ahead = cursor.fetchone()[0]

    connection.close()
    user_rank = users_ahead + 1
    return user_rank

async def get_leaderboard_users(lbData, bot):
    users = []
    for user_id, total_seconds in lbData:
        user = bot.get_user(user_id)
        if not user:
            try:
                user = await bot.fetch_user(user_id)
            except discord.NotFound:
                user = None
        
        username = user.name if user else f"Unknown User ({user_id})"
        users.append((username, total_seconds))
    return users

# ==========================================
#  PROFILE COMMAND
# ==========================================
@bot.tree.command(name="profile", description="View Your Profile")
async def Profile(interaction: discord.Interaction):
    userID = interaction.user.id
    lvl = level(interaction.user.id)
    solid_square = '\u25a0'
    hollow_square = '\u25a1'
    pAch = int(lvl[2] / lvl[1] * 10)
    
    desp = f'''```
Username    = {interaction.user.name}
Level       = {lvl[0]}
Daily Rank  = {get_user_rank(lbtype="daily", userID=interaction.user.id)}
Server Rank = {get_user_rank(lbtype="all time", userID=interaction.user.id)}
```'''
    
    profileEmbed = discord.Embed(
        title=f"{interaction.user.name}'s Profile",
        color=discord.Color.red(),
        description=desp
    )
    profileEmbed.set_thumbnail(url=interaction.user.avatar)
    profileEmbed.add_field(name="XP", value=f"{pAch*solid_square+((10-pAch)*hollow_square)}", inline=False)
    profileEmbed.add_field(name="Today Study Time", value=f"Total Time: {str(timedelta(seconds=int(getUserDailyTime(interaction.user.id))))}", inline=False)
    profileEmbed.add_field(name="Total Study Time", value=f"Total Time: {str(timedelta(seconds=int(getUserTime(interaction.user.id))))}", inline=False)
    profileEmbed.set_footer(
        text="Thanks for using our server. Keep Studying!",
        icon_url=interaction.guild.icon
    )
    await interaction.response.send_message(embed=profileEmbed)

# ==========================================
#  VOICE TRACKING  (tag-aware)
# ==========================================

# Tracks which DM message holds the tag selector so we can clean it up later.
# { userID: discord.Message }
_tag_prompt_messages: dict[int, discord.Message] = {}


def _flush_user_voice_time(userID: int) -> None:
    """
    Commits elapsed voice time to both the global tracker and the active tag
    tracker, then resets the session start to now (used when switching tags
    mid-session or during periodic flushes).
    """
    if userID not in voiceTrack:
        return
    now = datetime.now(timezone.utc)
    duration = (now - voiceTrack[userID]).total_seconds()
    if duration <= 0:
        return

    SaveUserTime(userID, duration)

    tag = getActiveTag(userID)
    if tag:
        SaveUserTimeByTag(userID, tag, duration)

    voiceTrack[userID] = now
    save_voice_sessions(voiceTrack)


def _build_tag_prompt_embed(tags: list[str]) -> discord.Embed:
    """Builds the tag selection embed. Shared between first send and after a tag is added."""
    if tags:
        desc = (
            "Select a subject tag from the dropdown so your study time is tracked correctly.\n"
            "Don't see your subject? Click **➕ Add Tag** to add one.\n\n"
            "You can switch anytime with `/switch_tag`."
        )
    else:
        desc = (
            "You don't have any subject tags yet.\n"
            "Click **➕ Add Tag** below to add your first one — then select it to start tracking!"
        )
    embed = discord.Embed(title="📚 What are you studying?", description=desc, color=discord.Color.blurple())
    embed.set_footer(text="No selection? Time still counts — just without a subject tag.")
    return embed


async def _send_tag_prompt(member: discord.Member, channel: discord.VoiceChannel) -> None:
    """Sends the tag-selection embed into the voice channel's built-in text chat."""

    # Delete any previous prompt for this user
    old_msg = _tag_prompt_messages.pop(member.id, None)
    if old_msg:
        try:
            await old_msg.delete()
        except Exception:
            pass

    tags = getUserTags(member.id)
    view = TagSelectView(member.id, tags)
    embed = _build_tag_prompt_embed(tags)

    try:
        msg = await channel.send(content=member.mention, embed=embed, view=view)
        _tag_prompt_messages[member.id] = msg
        view.message = msg
    except discord.Forbidden:
        pass


class AddTagModal(discord.ui.Modal, title="Add a Course Tag"):
    """Modal that lets a user add a new tag directly from the voice channel prompt."""
    tag_input = discord.ui.TextInput(
        label="Subject / Course name",
        placeholder="e.g. Math, Python, Biology...",
        min_length=1,
        max_length=MAX_TAG_LENGTH
    )

    def __init__(self, user_id: int):
        super().__init__()
        self.user_id = user_id

    async def on_submit(self, interaction: discord.Interaction):
        tag = self.tag_input.value.strip()
        result = addUserTag(self.user_id, tag)

        if result == 'limit':
            return await interaction.response.send_message(
                f"❌ You've reached the **{MAX_TAGS} tag limit**. Remove one with `/remove_tag` first.",
                ephemeral=True
            )
        if result == 'duplicate':
            await interaction.response.send_message(
                f"⚠️ **`{tag}`** is already in your tags. Select it from the dropdown!",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"✅ **`{tag}`** added! Now select it from the dropdown below.",
                ephemeral=True
            )

        # Rebuild the prompt with the updated tag list
        tags = getUserTags(self.user_id)
        new_view = TagSelectView(self.user_id, tags)
        new_embed = _build_tag_prompt_embed(tags)

        old_msg = _tag_prompt_messages.get(self.user_id)
        if old_msg:
            try:
                await old_msg.edit(embed=new_embed, view=new_view)
                new_view.message = old_msg
            except Exception:
                pass


class TagSelectView(discord.ui.View):
    def __init__(self, user_id: int, tags: list[str]):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.message: discord.Message | None = None

        if tags:
            self.add_item(TagDropdown(user_id, tags))

        self.add_item(AddTagButton(user_id))

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(
                    content="⏰ Tag selection expired. Use `/switch_tag` anytime to set one.",
                    view=self
                )
            except Exception:
                pass
        _tag_prompt_messages.pop(self.user_id, None)


class TagDropdown(discord.ui.Select):
    def __init__(self, user_id: int, tags: list[str]):
        self.user_id = user_id
        options = [discord.SelectOption(label=tag, value=tag, emoji="🏷️") for tag in tags]
        super().__init__(placeholder="Choose your subject tag...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("This isn't your session!", ephemeral=True)

        chosen_tag = self.values[0]
        _flush_user_voice_time(self.user_id)
        setActiveTag(self.user_id, chosen_tag)

        embed = discord.Embed(
            description=f"✅ Now tracking under **`{chosen_tag}`**.\nUse `/switch_tag` to change subjects.",
            color=discord.Color.green()
        )
        await interaction.response.edit_message(content=None, embed=embed, view=None)
        _tag_prompt_messages.pop(self.user_id, None)


class AddTagButton(discord.ui.Button):
    def __init__(self, user_id: int):
        super().__init__(label="➕ Add Tag", style=discord.ButtonStyle.secondary)
        self.user_id = user_id

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("This isn't your session!", ephemeral=True)
        await interaction.response.send_modal(AddTagModal(self.user_id))


@bot.event
async def on_voice_state_update(member, before, after):
    userID = member.id
    guild_id = member.guild.id
    exChannels = getExChannel(guild_id)

    was_tracking = userID in voiceTrack
    is_now_tracking = (after.channel is not None) and (after.channel.id not in exChannels)

    # ── User left a tracked channel (or moved to an excluded one) ──
    if was_tracking and (not is_now_tracking or (before.channel and before.channel.id != after.channel.id)):
        joinTime = voiceTrack.pop(userID)
        leaveTime = datetime.now(timezone.utc)
        duration = (leaveTime - joinTime).total_seconds()

        SaveUserTime(userID, duration)

        tag = getActiveTag(userID)
        if tag:
            SaveUserTimeByTag(userID, tag, duration)

        clearActiveTag(userID)
        save_voice_sessions(voiceTrack)

        # Clean up any pending DM prompt
        old_msg = _tag_prompt_messages.pop(userID, None)
        if old_msg:
            try:
                await old_msg.delete()
            except Exception:
                pass

    # ── User joined a tracked channel ──
    if is_now_tracking and userID not in voiceTrack:
        voiceTrack[userID] = datetime.now(timezone.utc)
        save_voice_sessions(voiceTrack)
        # Send the tag selection prompt via DM
        await _send_tag_prompt(member, after.channel)


# ==========================================
#  SWITCH TAG COMMAND
# ==========================================
@bot.tree.command(name="switch_tag", description="Switch the subject tag your current study session is tracked under")
async def switch_tag(interaction: discord.Interaction):
    userID = interaction.user.id

    # Must be in a tracked voice channel
    if userID not in voiceTrack:
        return await interaction.response.send_message(
            "❌ You're not in a study channel right now. Join one first!",
            ephemeral=True
        )

    tags = getUserTags(userID)
    if not tags:
        return await interaction.response.send_message(
            "❌ You don't have any tags set up. Use `/add_tag` to add your subjects first.",
            ephemeral=True
        )

    current_tag = getActiveTag(userID)
    current_display = f"`{current_tag}`" if current_tag else "*none*"

    view = SwitchTagView(userID, tags, current_tag)

    embed = discord.Embed(
        title="🔀 Switch Study Tag",
        description=(
            f"**Currently tracking:** {current_display}\n\n"
            "Select a new subject tag below.\n"
            "Time already spent under the current tag is saved automatically."
        ),
        color=discord.Color.blurple()
    )

    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


class SwitchTagView(discord.ui.View):
    def __init__(self, user_id: int, tags: list[str], current_tag: str | None):
        super().__init__(timeout=120)
        self.add_item(SwitchTagDropdown(user_id, tags, current_tag))


class SwitchTagDropdown(discord.ui.Select):
    def __init__(self, user_id: int, tags: list[str], current_tag: str | None):
        self.user_id = user_id
        options = []
        for tag in tags:
            is_active = (tag == current_tag)
            options.append(discord.SelectOption(
                label=tag,
                value=tag,
                emoji="✅" if is_active else "🏷️",
                description="Currently active" if is_active else None
            ))
        super().__init__(
            placeholder="Choose a new subject tag...",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message(
                "This isn't your session!", ephemeral=True
            )

        chosen_tag = self.values[0]
        old_tag = getActiveTag(self.user_id)

        if chosen_tag == old_tag:
            return await interaction.response.edit_message(
                content=f"ℹ️ You're already studying under **`{chosen_tag}`**.",
                embed=None, view=None
            )

        # Flush accumulated time under the OLD tag before switching
        _flush_user_voice_time(self.user_id)

        setActiveTag(self.user_id, chosen_tag)

        embed = discord.Embed(
            description=(
                f"✅ Switched to **`{chosen_tag}`**.\n"
                + (f"Time under **`{old_tag}`** has been saved." if old_tag else "")
            ),
            color=discord.Color.green()
        )
        await interaction.response.edit_message(content=None, embed=embed, view=None)
# ==========================================
#  LEADERBOARD  (unified helper + view)
# ==========================================

AIOHTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://discord.com/"
}

async def _build_leaderboard_image(bot_ref, lb_type: str, author_id: int):
    """
    Fetches + processes leaderboard data for the given lb_type.
    Returns (file, header_msg) ready to send.
    lb_type: "daily" | "weekly" | "all time"
    """
    flush_active_voice_time()
    processed_users = []

    async with aiohttp.ClientSession(headers=AIOHTTP_HEADERS) as session:

        # ── DAILY ──────────────────────────────────────────────────────────
        if lb_type == "daily":
            ranked_data, user_rank = get_contextual_data(author_id, 'daily')
            if not ranked_data:
                return None, None

            for rank, uid, seconds in ranked_data:
                user = bot_ref.get_user(uid) or await _safe_fetch_user(bot_ref, uid)
                username = user.display_name if user else f"Unknown ({uid})"
                avatar_bytes = await _fetch_avatar(session, user)
                h, m = divmod(int(seconds) // 60, 60)
                processed_users.append({
                    'rank': rank, 'name': username,
                    'time': f"{h}h {m}m", 'avatar_bytes': avatar_bytes,
                    'is_target': (uid == author_id)
                })

            header = f"📅 **Daily Leaderboard** | Your Rank: **#{user_rank}**"
            filename = "daily_leaderboard.png"

        # ── WEEKLY ─────────────────────────────────────────────────────────
        elif lb_type == "weekly":
            raw_data = get_weekly_leaderboard(offset=0)
            if not raw_data:
                return None, None

            user_rank = get_weekly_rank(author_id)

            for rank, (uid, seconds) in enumerate(raw_data, start=1):
                user = bot_ref.get_user(uid) or await _safe_fetch_user(bot_ref, uid)
                username = user.display_name if user else f"Unknown ({uid})"
                avatar_bytes = await _fetch_avatar(session, user)
                h, m = divmod(int(seconds) // 60, 60)
                is_target = (uid == author_id)
                processed_users.append({
                    'rank': rank, 'name': username,
                    'time': f"{h}h {m}m", 'avatar_bytes': avatar_bytes,
                    'is_target': is_target
                })

            header = f"📆 **Weekly Leaderboard** | Your Rank: **#{user_rank}**"
            filename = "weekly_leaderboard.png"

        # ── ALL TIME ───────────────────────────────────────────────────────
        else:
            raw_data = get_leaderboard_data('all time', offset=0)
            if not raw_data:
                return None, None

            for uid, seconds in raw_data:
                user = bot_ref.get_user(uid) or await _safe_fetch_user(bot_ref, uid)
                username = user.display_name if user else f"Unknown ({uid})"
                avatar_bytes = await _fetch_avatar(session, user)
                h, m = divmod(int(seconds) // 60, 60)
                processed_users.append({
                    'name': username, 'time': f"{h}h {m}m",
                    'avatar_bytes': avatar_bytes
                })

            header = "🏆 **All Time Leaderboard**"
            filename = "alltime_leaderboard.png"

    final_buffer = await bot.loop.run_in_executor(None, draw_leaderboard, processed_users)
    file = discord.File(fp=final_buffer, filename=filename)
    return file, header


async def _safe_fetch_user(bot_ref, uid):
    try:
        return await bot_ref.fetch_user(uid)
    except Exception:
        return None


async def _fetch_avatar(session, user) -> bytes | None:
    if not user:
        return None
    try:
        async with session.get(user.display_avatar.url) as resp:
            if resp.status == 200:
                return await resp.read()
    except Exception:
        pass
    return None


class LeaderboardView(discord.ui.View):
    """Unified leaderboard view with Daily / Weekly / All Time tab buttons."""

    def __init__(self, author_id: int, lb_type: str):
        super().__init__(timeout=3600)
        self.author_id = author_id
        self.lb_type   = lb_type
        self.message   = None
        self._update_buttons()

    def _update_buttons(self):
        """Re-render buttons so the active tab is highlighted."""
        self.clear_items()

        styles = {
            "daily":    discord.ButtonStyle.primary if self.lb_type == "daily"    else discord.ButtonStyle.secondary,
            "weekly":   discord.ButtonStyle.primary if self.lb_type == "weekly"   else discord.ButtonStyle.secondary,
            "all time": discord.ButtonStyle.primary if self.lb_type == "all time" else discord.ButtonStyle.secondary,
        }
        self.add_item(_TabButton("📅 Daily",    "daily",    styles["daily"]))
        self.add_item(_TabButton("📆 Weekly",   "weekly",   styles["weekly"]))
        self.add_item(_TabButton("🏆 All Time", "all time", styles["all time"]))
        self.add_item(_RefreshButton())
        self.add_item(_DeleteButton())

    async def switch_to(self, interaction: discord.Interaction, new_type: str):
        if new_type == self.lb_type:
            return await interaction.response.defer()

        await interaction.response.defer()   # acknowledge immediately — prevents "Interaction failed"
        self.lb_type = new_type
        self._update_buttons()
        await self._do_edit(interaction)

    async def refresh(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await self._do_edit(interaction)

    async def _edit(self, interaction: discord.Interaction):
        # Legacy entry point — defer then edit
        await interaction.response.defer()
        await self._do_edit(interaction)

    async def _do_edit(self, interaction: discord.Interaction):
        """Core edit logic — always called AFTER the interaction has been deferred."""
        file, header = await _build_leaderboard_image(interaction.client, self.lb_type, self.author_id)

        if file is None:
            return await interaction.followup.send("No data available yet!", ephemeral=True)

        # edit_original_response works correctly after defer(), unlike message.edit()
        await interaction.edit_original_response(content=header, attachments=[file], view=self)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except Exception:
                pass


class _TabButton(discord.ui.Button):
    def __init__(self, label: str, lb_type: str, style: discord.ButtonStyle):
        super().__init__(label=label, style=style)
        self.lb_type = lb_type

    async def callback(self, interaction: discord.Interaction):
        # switch_to handles defer internally
        await self.view.switch_to(interaction, self.lb_type)


class _RefreshButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="🔄 Refresh", style=discord.ButtonStyle.secondary, row=1)

    async def callback(self, interaction: discord.Interaction):
        # refresh handles defer internally
        await self.view.refresh(interaction)


class _DeleteButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="🗑 Delete", style=discord.ButtonStyle.danger, row=1)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.view.author_id:
            return await interaction.response.send_message(
                "Only the command author can delete this.", ephemeral=True
            )
        await interaction.message.delete()


# ==========================================
#  LEADERBOARD COMMANDS
# ==========================================
@bot.tree.command(name="leaderboard", description="View the study leaderboard — Daily, Weekly or All Time")
@app_commands.describe(tab="Which leaderboard to open first (default: Daily)")
@app_commands.choices(tab=[
    app_commands.Choice(name="Daily",    value="daily"),
    app_commands.Choice(name="Weekly",   value="weekly"),
    app_commands.Choice(name="All Time", value="all time"),
])
async def leaderboard(interaction: discord.Interaction, tab: app_commands.Choice[str] = None):
    await interaction.response.defer()
    lb_type = tab.value if tab else "daily"

    file, header = await _build_leaderboard_image(bot, lb_type, interaction.user.id)

    if file is None:
        return await interaction.followup.send("No data recorded yet! Start studying to appear here.")

    view = LeaderboardView(interaction.user.id, lb_type)
    msg = await interaction.followup.send(content=header, file=file, view=view)
    view.message = msg


@bot.command(aliases=('lb', 'rank'))
async def lb_text(ctx, page: int = 1):
    """Prefix command fallback — plain text all-time leaderboard."""
    offset = (page - 1) * 10
    lbData = get_leaderboard_data('all time', offset=offset)

    if not lbData:
        return await ctx.send("No data found for this page.")

    user_list = await get_leaderboard_users(lbData, bot)

    lbEmbed = discord.Embed(title='🏆 All Time Study Leaderboard', color=discord.Color.gold())
    if ctx.guild.icon:
        lbEmbed.set_thumbnail(url=ctx.guild.icon.url)

    longest_name = max((len(u[0]) for u in user_list), default=0)
    start_rank = offset + 1

    for rank, (username, total_seconds) in enumerate(user_list, start=start_rank):
        minutes, seconds = divmod(int(total_seconds), 60)
        hours, minutes = divmod(minutes, 60)
        lbEmbed.add_field(
            name=f"#{rank} - {username.ljust(longest_name)}",
            value=f"⏱️ {hours}h {minutes}m {seconds}s",
            inline=False
        )

    await ctx.send(embed=lbEmbed)

# ==========================================
#  TASK SYSTEM
# ==========================================
@bot.tree.command(name="add_task", description="add a Journal or Daily task")
@app_commands.choices(task_type=[
    app_commands.Choice(name="Journal", value="journal"),
    app_commands.Choice(name="Daily", value="daily")
])
async def add_task(interaction: discord.Interaction, task_name: str, task_type: app_commands.Choice[str]):
    type_val = task_type.value
    
    data = getUserData(interaction.user.id)
    new_task = {"name": task_name, "completed": False}
    
    data[type_val].append(new_task)
        
    SaveUserTasks(interaction.user.id, data["journal"], data["daily"])
    await interaction.response.send_message(f"✅ Added {type_val} task: **{task_name}**", ephemeral=True)

class TaskSelect(discord.ui.Select):
    def __init__(self, user_id, journal_tasks, daily_tasks):
        options = []
        
        for i, t in enumerate(journal_tasks):
            if not t['completed']:
                options.append(discord.SelectOption(
                    label=f"Journal: {t['name']}", 
                    value=f"journal_{i}",
                    emoji="📝"
                ))
        
        for i, t in enumerate(daily_tasks):
            if not t['completed']:
                options.append(discord.SelectOption(
                    label=f"Daily: {t['name']}", 
                    value=f"daily_{i}",
                    emoji="☀️"
                ))

        if not options:
            options.append(discord.SelectOption(label="All tasks completed!", value="none"))
            super().__init__(placeholder="Nothing left to do!", options=options, disabled=True)
        else:
            super().__init__(placeholder="Select a task to complete...", options=options)

    async def callback(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        data = getUserData(user_id)
        
        task_type, index = self.values[0].split("_")
        index = int(index)
        
        data[task_type][index]['completed'] = True
        
        SaveUserTasks(user_id, data['journal'], data['daily'])
        
        await interaction.response.send_message(
            f"✅ Marked **{data[task_type][index]['name']}** as completed!", 
            ephemeral=True
        )

class TaskView(discord.ui.View):
    def __init__(self, user_id, journal, daily):
        super().__init__()
        self.add_item(TaskSelect(user_id, journal, daily))

@bot.tree.command(name="complete", description="Check off your study tasks for the day")
async def complete(interaction: discord.Interaction):
    user_id = interaction.user.id
    data = getUserData(user_id)
    
    if not data['journal'] and not data['daily']:
        return await interaction.response.send_message(
            "You don't have any tasks set! Use `/add_task` first.", 
            ephemeral=True
        )
    
    view = TaskView(user_id, data['journal'], data['daily'])
    await interaction.response.send_message("Select a task to mark it as finished:", view=view, ephemeral=True)
# ==========================================
#  TASK BUTTON VIEW
# ==========================================
class TaskButtonsView(discord.ui.View):
    def __init__(self, author_id):
        super().__init__(timeout=3600)  # increase timeout
        self.author_id = author_id
    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            await self.message.edit(view=self)

       

    @discord.ui.button(label="🔄 Refresh", style=discord.ButtonStyle.primary)
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):

        if interaction.user.id != self.author_id:
            return await interaction.response.send_message(
                "You cannot refresh someone else's task list.",
                ephemeral=True
            )

        data = getUserData(self.author_id)
        info = get_streak_info(self.author_id)

        embed = build_tasks_embed(interaction.user, data, info)

        await interaction.response.edit_message(embed=embed, view=self)
        


    @discord.ui.button(label="🗑 Delete", style=discord.ButtonStyle.danger)
    async def delete(self, interaction: discord.Interaction, button: discord.ui.Button):

        if interaction.user.id != self.author_id:
            return await interaction.response.send_message(
                "You cannot delete someone else's task list.",
                ephemeral=True
            )

        await interaction.message.delete()
 
def build_tasks_embed(user, data, info):
    embed = discord.Embed(color=discord.Color.blue())

    embed.set_author(
        name=f"{user.display_name}'s Task List",
        icon_url=user.display_avatar.url
    )

    streak_emojis = get_digit_emojis(info['streak'])
    tick = CUSTOM_EMOJIS['tick']
    cross = CUSTOM_EMOJIS['cross']

    j_list = "\n".join(
        [f"{tick if t['completed'] else cross} {t['name']}" for t in data['journal']]
    ) or "None"

    d_list = "\n".join(
        [f"{tick if t['completed'] else cross} {t['name']}" for t in data['daily']]
    ) or "None"

    embed.description = (
        f"**Current Streak:** {streak_emojis} days\n\n"
        f"**Journal Tasks:**\n{j_list}\n\n"
        f"**Daily Tasks:**\n{d_list}"
    )

    return embed      
# Custom Emoji Mapping
CUSTOM_EMOJIS = {
    '0': '<a:number0:1474683361653162114>',
    '1': '<a:number1:1474683366531137717>',
    '2': '<a:number2:1474683397262807110>',
    '3': '<a:number3:1474683392682627135>',
    '4': '<a:number4:1474683388534198404>',
    '5': '<a:number5:1474683383886909542>',
    '6': '<a:number6:1474683364215885896>',
    '7': '<a:number7:1474683374495862946>',
    '8': '<a:number8:1474683378304417832>',
    '9': '<a:number9:1474683358351982725>',
    'tick':'<:tick_green:1474680197273096243>',
    'cross':'<:cross_red:1474680228939829298>'
}

COMPLETE_CMD = "</complete:1465995376103391290>" 
ADD_TASK_CMD = "</add_task:1465995376103391289>"

# Helper function to convert integers to your custom digit emojis
def get_digit_emojis(number: int) -> str:
    return "".join(CUSTOM_EMOJIS.get(char, char) for char in str(number))
#task list command
@bot.tree.command(name="tasks", description="View your current task list and streak status")
async def view_tasks(interaction: discord.Interaction):
    user_id = interaction.user.id
    data = getUserData(user_id)
    info = get_streak_info(user_id)
    
    msg_content = (
        f"Hello **{interaction.user.display_name}**!\n\n"
        "Here are the tasks for the remaining day!\n"
        f" {COMPLETE_CMD} a task\n"
        f" {ADD_TASK_CMD} a new task\n\n"
        " Good Luck! ✨"
    )

    embed = build_tasks_embed(interaction.user, data, info)
    # 3. Send both the content and the embed
    view = TaskButtonsView(user_id)
    await interaction.response.send_message(content=msg_content, embed=embed, view=view)
    view.message = await interaction.original_response()

# ==========================================
#  STREAK LEADERBOARD
# ==========================================
@bot.tree.command(name="streak_leaderboard", description="View the Top 10 Active Streaks")
async def streak_img_lb(interaction: discord.Interaction):
    # 1. Defer immediately so Discord knows we are working
    await interaction.response.defer()

    try:
        # 2. Fetch Data
        raw_data = get_streak_leaderboard()
        
        if not raw_data:
            return await interaction.followup.send("No active streaks found! Start studying to get on the board.")

        processed_users = []
        
        # 3. Process Data (Safely)
        print(f"DEBUG: Processing {len(raw_data)} streak entries...") # Console Log
        
        for index, row in enumerate(raw_data):
            # SAFETY CHECK: Ensure row has enough data
            if len(row) < 2:
                print(f"Skipping malformed row: {row}")
                continue
                
            # Access by INDEX instead of unpacking (Fixes 'too many values' error)
            user_id = row[0]
            streak_val = row[1]
            
            # Fetch User
            user = bot.get_user(user_id)
            if not user:
                try:
                    user = await bot.fetch_user(user_id)
                except:
                    user = None
            
            username = user.display_name if user else "Unknown User"
            
            processed_users.append({
                'name': username,
                'streak': str(streak_val)
            })

        # 4. Generate Image (with specific error catch)
        try:
            print("DEBUG: Generating Image...")
            final_buffer = await bot.loop.run_in_executor(None, draw_streak_leaderboard, processed_users)
            file = discord.File(fp=final_buffer, filename="streak_leaderboard.png")
            
            # 5. Send Success
            await interaction.followup.send(file=file)
            print("DEBUG: Sent Streak Leaderboard.")
            
        except Exception as img_error:
            print(f"❌ IMAGE GEN ERROR: {img_error}")
            import traceback
            traceback.print_exc()
            await interaction.followup.send("Error generating the image file. Check console logs.")

    except Exception as e:
        # Catch any other logic errors (like database connection failing)
        print(f"❌ CRITICAL ERROR: {e}")
        await interaction.followup.send(f"An error occurred: {str(e)}")
MOTIVATIONAL_LINES = [
    "Every hour you put in today is a brick.\nYou might not see the building yet — but it's going up. 🏗️",
    "Whether today was a 10/10 grind or barely getting through — you showed up.\nThat already puts you ahead. 💪",
    "Consistency over intensity. Keep stacking the days. 🔥",
    "Small progress is still progress. You're building something real. 📈",
    "The version of you from a month ago would be proud. Keep going. ⭐",
]

async def send_daily_reports(user_ids: list[int]) -> None:
    """
    DMs every user who studied today a personalised end-of-day report embed
    with their stats image (pie chart by tag + 7-day bar chart).
    """
    today_str = datetime.now(timezone.utc).strftime("%d/%m/%Y")

    for userID in user_ids:
        try:
            user = bot.get_user(userID)
            if not user:
                try:
                    user = await bot.fetch_user(userID)
                except Exception:
                    continue

            # ── Gather data ──────────────────────────────────────────────
            daily_secs   = getUserDailyTime(userID)
            tag_times    = getUserTagTimes(userID)       # [(tag, total_secs), ...]
            history      = get_last_7_days(userID)       # [(date, secs), ...] len=7
            streak_info  = get_streak_info(userID)

            hours_today  = daily_secs / 3600
            time_str     = f"{int(hours_today)}h {int((hours_today % 1) * 60)}m" \
                           if hours_today >= 1 else \
                           f"{int(daily_secs // 60)}m"

            # ── Generate stats image in executor ─────────────────────────
            stats_buffer = await bot.loop.run_in_executor(
                None, generate_stats_image, tag_times, history
            )

            # ── Fetch user avatar ─────────────────────────────────────────
            avatar_url = user.display_avatar.url

            # ── Build embed ───────────────────────────────────────────────
            motivational = random.choice(MOTIVATIONAL_LINES)
            streak_val   = streak_info.get("streak", 0)
            streak_line  = f"🔥 Current streak: **{streak_val} day{'s' if streak_val != 1 else ''}**" \
                           if streak_val > 0 else ""

            embed = discord.Embed(
                color=discord.Color.from_rgb(240, 165, 0),   # gold accent
                timestamp=datetime.now(timezone.utc)
            )

            embed.description = (
                f"**Great work for the day! You've studied {time_str} on SISB.**\n\n"
                f"Hope you ended this day on a high note. Here is your report for the day, "
                f"here's to hoping you will aim to do more. 🌙\n\n"
                f"{motivational}\n\n"
                + (f"{streak_line}\n\n" if streak_line else "")
                + f"Thank you for using SISB today, as always:\n"
                  f"*\"Stay consistent, Do more, Be better\"* 🧡"
            )

            embed.set_author(
                name=f"Dear @{user.name}",
                icon_url=avatar_url
            )

            embed.set_image(url="attachment://daily_stats.png")

            embed.set_footer(
                text=f"Team South Indian Study Buddies  •  {today_str}"
            )

            stats_file = discord.File(fp=stats_buffer, filename="daily_stats.png")

            await user.send(embed=embed, file=stats_file)
            print(f"📬 Report sent to {user.name} ({userID})")

        except discord.Forbidden:
            print(f"⚠️ Could not DM user {userID} — DMs closed")
        except Exception as e:
            print(f"❌ Error sending report to {userID}: {e}")

# ==========================================
#  SCHEDULED TASKS
# ==========================================
MAINTENANCE_TIME = time(hour=23, minute=25, tzinfo=timezone.utc)
STREAK_CHANNEL_ID = 1464650405278515444
DAILY_TIME = time(hour=23, minute=30, tzinfo=timezone.utc)
PING_ROLE_ID = 1474670431167451257

@tasks.loop(time=MAINTENANCE_TIME)
async def midnight_maintenance():
    print("🕛 4:55 AM IST: RUNNING MAINTENANCE & STREAK UPDATES")
    
    task_conn = sqlite3.connect('userTaskList.db')
    time_conn = sqlite3.connect('userTimeUsage.db')
    
    task_cursor = task_conn.cursor()
    time_cursor = time_conn.cursor()

    task_cursor.execute("SELECT userID, tasks FROM userTasks")
    all_users = task_cursor.fetchall()
    user_tasks_map = {}
    for userID, tasks_json in all_users:
        # Keep the row with the longest string (most tasks) to avoid empty duplicates
        if userID not in user_tasks_map or len(tasks_json) > len(user_tasks_map[userID]):
            user_tasks_map[userID] = tasks_json

    yesterday_str = (datetime.now(timezone.utc) - timedelta(days=1)).strftime('%Y-%m-%d')

    for userID, tasks_json in all_users:
        try:
            data = json.loads(tasks_json)
            journal_tasks = data.get("journal", [])
            daily_tasks = data.get("daily", [])

            if not journal_tasks and not daily_tasks:
                is_eligible = False
            else:
                journal_done = all(t.get('completed', False) for t in journal_tasks)
                daily_done = all(t.get('completed', False) for t in daily_tasks)
                is_eligible = journal_done and daily_done

            if is_eligible:
                time_cursor.execute('''
                    UPDATE userTime 
                    SET current_streak = COALESCE(current_streak, 0) + 1,  
                        streak_status = 'ACTIVE',
                        last_completion_date = ?
                    WHERE userID = ?
                ''', (yesterday_str, userID))
            else:
                time_cursor.execute('''
                    UPDATE userTime 
                    SET current_streak = 0, 
                        streak_status = 'INACTIVE'
                    WHERE userID = ?
                ''', (userID,))

            for t in journal_tasks:
                t['completed'] = False
            
            new_tasks_data = json.dumps({"journal": journal_tasks, "daily": []})
            task_cursor.execute("UPDATE userTasks SET tasks = ? WHERE userID = ?", (new_tasks_data, userID))
            
        except Exception as e:
            print(f"Error processing user {userID}: {e}")

    task_conn.commit()
    time_conn.commit()
    task_conn.close()
    time_conn.close()

    current_time = datetime.now(timezone.utc)
    
    for userID, start_time in list(voiceTrack.items()):
        duration = (current_time - start_time).total_seconds()
        SaveUserTime(userID, duration)
        tag = getActiveTag(userID)
        if tag:
            SaveUserTimeByTag(userID, tag, duration)
        voiceTrack[userID] = current_time
    save_voice_sessions(voiceTrack)

    # ── Snapshot today's time for each user BEFORE the reset ──
    conn_snap = sqlite3.connect('userTimeUsage.db')
    snap_cursor = conn_snap.cursor()
    snap_cursor.execute('SELECT userID FROM userTime WHERE daily_time > 0')
    active_today = [row[0] for row in snap_cursor.fetchall()]
    conn_snap.close()

    for userID in active_today:
        snapshotDailyTime(userID)

    # ── Send DM report to every user who studied today ──
    await send_daily_reports(active_today)

    conn_lb = sqlite3.connect('userTimeUsage.db')
    cursor_lb = conn_lb.cursor()
    cursor_lb.execute('UPDATE userTime SET daily_time = 0')
    conn_lb.commit()
    conn_lb.close()
    print("✅ Daily leaderboard reset.")

@tasks.loop(time=DAILY_TIME)
async def post_daily_streak():
    channel = bot.get_channel(STREAK_CHANNEL_ID)
    
    if not channel:
        print(f"❌ Error: Could not find channel with ID {STREAK_CHANNEL_ID}")
        return

    try:
        async for message in channel.history(limit=20):
            if message.author == bot.user and "Daily Streak Leaderboard" in message.content:
                await message.delete()
                break
    except Exception as e:
        print(f"Error deleting old message: {e}")

    try:
        raw_data = get_streak_leaderboard()
        
        if not raw_data:
            await channel.send("Daily Streak Leaderboard: No active streaks today!")
            return

        processed_users = []
        for user_id, streak in raw_data:
            user = bot.get_user(user_id)
            if not user:
                try:
                    user = await bot.fetch_user(user_id)
                except:
                    user = None
            
            username = user.display_name if user else "Unknown User"
            processed_users.append({'name': username, 'streak': str(streak)})

        final_buffer = await bot.loop.run_in_executor(None, draw_streak_leaderboard, processed_users)
        file = discord.File(fp=final_buffer, filename="daily_streak.png")

        await channel.send(f"<@&{PING_ROLE_ID}> 🔥 Daily Streak Leaderboard 🔥\nKeep the grind going!", file=file)
        
    except Exception as e:
        print(f"Error generating daily streak: {e}")

# ==========================================
#  MESSAGE HANDLER (REP SYSTEM)
# ==========================================
@bot.event
async def on_message(message):
    if message.author.bot:
        return
        
    msg_content = message.content.lower()
    thank_keywords = ["thanks", "thank you", "thx", "tysm"]
    
    if any(word in msg_content for word in thank_keywords):
        thanked_user = None

        if message.reference:
            try:
                original_msg = message.reference.resolved
                if not original_msg:
                    original_msg = await message.channel.fetch_message(message.reference.message_id)
                thanked_user = original_msg.author
            except Exception:
                pass

        if not thanked_user and message.mentions:
            for user in message.mentions:
                if user.id != message.author.id:
                    thanked_user = user
                    break
                
            if not thanked_user and message.mentions:
                thanked_user = message.mentions[0]

        if thanked_user:
            try:
                if thanked_user.id == message.author.id:
                    await message.channel.send(f"{message.author.mention}, you can't rep yourself! Nice try though. 😉")
                elif thanked_user.bot:
                    await message.channel.send(f"I appreciate it, {message.author.mention}, but I don't need reps! 🤖")
                else:
                    total_reps = add_rep(thanked_user.id)
                    
                    embed = discord.Embed(
                        description=f"**Thanks {thanked_user.mention} for helping {message.author.mention}!**\n\n🎉 You gained a rep!\n📈 **Your Total Reps:** `{total_reps}`",
                        color=discord.Color.blue()
                    )
                    
                    embed.set_thumbnail(url=thanked_user.display_avatar.url)

                    embed.set_footer(
                        text="Thanks for the Good Work! Keep it up.",
                        icon_url=message.guild.icon.url if message.guild.icon else None
                    )
                    
                    await message.channel.send(embed=embed)
                    
            except Exception as e:
                print(f"Error in rep system: {e}")

    await check_humor(message)
    await bot.process_commands(message)

# ==========================================
#  TAGS SYSTEM
# ==========================================
@bot.tree.command(name="add_tag", description="Add a course tag to your profile")
@app_commands.describe(tag="The course or subject tag to add (e.g. Math, Python, Biology)")
async def add_tag(interaction: discord.Interaction, tag: str):

    if len(tag.strip()) > MAX_TAG_LENGTH:
        return await interaction.response.send_message(
            f"❌ Tag is too long! Keep it under **{MAX_TAG_LENGTH} characters**.",
            ephemeral=True
        )

    if len(tag.strip()) == 0:
        return await interaction.response.send_message(
            "❌ Tag cannot be empty.",
            ephemeral=True
        )

    result = addUserTag(interaction.user.id, tag)

    if result == 'added':
        tags = getUserTags(interaction.user.id)
        tags_display = "  ".join([f"`{t}`" for t in tags])

        embed = discord.Embed(
            description=f"✅ Added tag **`{tag.strip()}`** to your profile!\n\n**Your Tags:**\n{tags_display}",
            color=discord.Color.green()
        )
        embed.set_footer(text=f"{len(tags)}/{MAX_TAGS} tags used")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    elif result == 'duplicate':
        await interaction.response.send_message(
            f"⚠️ You already have the tag **`{tag.strip()}`** on your profile.",
            ephemeral=True
        )

    elif result == 'limit':
        await interaction.response.send_message(
            f"❌ You've reached the **{MAX_TAGS} tag limit**. Remove a tag first using `/remove_tag`.",
            ephemeral=True
        )


@bot.tree.command(name="remove_tag", description="Remove a course tag from your profile")
@app_commands.describe(tag="The tag you want to remove")
async def remove_tag(interaction: discord.Interaction, tag: str):

    result = removeUserTag(interaction.user.id, tag)

    if result == 'removed':
        tags = getUserTags(interaction.user.id)

        if tags:
            tags_display = "  ".join([f"`{t}`" for t in tags])
            remaining = f"\n\n**Remaining Tags:**\n{tags_display}"
        else:
            remaining = "\n\nYou have no tags left. Add one with `/add_tag`."

        embed = discord.Embed(
            description=f"🗑️ Removed tag **`{tag.strip()}`** from your profile.{remaining}",
            color=discord.Color.orange()
        )
        if tags:
            embed.set_footer(text=f"{len(tags)}/{MAX_TAGS} tags used")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    elif result == 'not_found':
        tags = getUserTags(interaction.user.id)
        tags_display = "  ".join([f"`{t}`" for t in tags]) if tags else "*(none)*"
        await interaction.response.send_message(
            f"❌ You don't have a tag called **`{tag.strip()}`**.\n\n**Your current tags:**\n{tags_display}",
            ephemeral=True
        )

    elif result == 'empty':
        await interaction.response.send_message(
            "❌ You don't have any tags yet. Add one with `/add_tag`.",
            ephemeral=True
        )

# ==========================================
#  BOT READY EVENT - MUST BE AFTER ALL COMMANDS
# ==========================================
@bot.event
async def on_ready():
    print("🤖 Bot is starting up...")
    
    # Setup databases
    setupTimeDB()
    setupTaskDB()
    setupExChannelDB()
    setupRepDB()
    setupTagsDB()
    setupTagTimeDB()
    setupDailyHistoryDB()
    
    # Start scheduled tasks
    if not midnight_maintenance.is_running():
        midnight_maintenance.start()
        print("✅ Midnight maintenance task started")
    
    if not post_daily_streak.is_running():
        post_daily_streak.start()
        print("✅ Daily streak post task started")

    # Add context menu
    bot.tree.add_command(report_menu)
    
    # Sync commands
    try:
        synced = await bot.tree.sync()
        print(f"✅ Synced {len(synced)} slash command(s)")
    except Exception as e:
        print(f"❌ Error syncing commands: {e}")
    
    print(f"✅ Bot is ready! Logged in as {bot.user}")

# ==========================================
#  FLASK WEB SERVER (RENDER KEEP-ALIVE)
# ==========================================
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is alive and running!"

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

# ==========================================
#  MAIN EXECUTION
# ==========================================
if __name__ == "__main__":
    # Start Flask in background thread
    web_thread = Thread(target=run_web, daemon=True)
    web_thread.start()
    print("✅ Flask web server started")

    # Start Discord bot (THIS MUST BE LAST)
    token = os.getenv('DISCORD_TOKEN')
    if token:
        print("🚀 Starting Discord bot...")
        bot.run(token)
    else:
        print("❌ ERROR: DISCORD_TOKEN not found in Environment Variables!")


#