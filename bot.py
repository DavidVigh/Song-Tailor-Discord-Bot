import os
import json
import logging
import aiohttp
from typing import List

import discord
from discord.ext import commands
from aiohttp import web

# Setup logging - Check Railway "Deploy Logs" to see the specific error if this fails
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("DiscordWebhookBot")

# Variables from Railway
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
TARGET_CHANNEL_ID = int(os.getenv("TARGET_CHANNEL_ID"))
WEBHOOK_PORT = int(os.getenv("WEBHOOK_PORT", 8080))
# 🔑 Use your JWT Secret as the Shared Secret
WEBHOOK_SECRET = os.getenv("SUPABASE_JWT_SECRET")

# Supabase Auth for fetching profiles
SUPABASE_URL = os.getenv("SUPABASE_URL") # Add this to Railway!
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") # Use Service Role Key!

class CarouselView(discord.ui.View):
    def __init__(self, tracks: List[dict]):
        super().__init__(timeout=None)
        self.tracks = [t for t in tracks if t.get('url')]
        self.current_index = 0
        self.update_buttons()

    def update_buttons(self):
        if not self.tracks: return
        self.back_btn.disabled = (self.current_index == 0)
        self.next_btn.disabled = (self.current_index == len(self.tracks) - 1)

    def get_embed(self) -> discord.Embed:
        if not self.tracks: return discord.Embed(title="No tracks available")
        track = self.tracks[self.current_index]
        embed = discord.Embed(
            title=f"🎼 Track Preview: {track.get('title', 'Untitled')}",
            url=track.get('url'),
            color=0x9b59b6 # Purple
        )
        # Extract YouTube ID for Thumbnail
        url = track.get('url', '')
        v_id = url.split('v=')[-1].split('&')[0] if 'v=' in url else url.split('/')[-1]
        embed.set_image(url=f"https://img.youtube.com/vi/{v_id}/mqdefault.jpg")
        embed.set_footer(text=f"Navigate Sneak Peaks ({self.current_index + 1}/{len(self.tracks)})")
        return embed

    @discord.ui.button(label="◀ Back", style=discord.ButtonStyle.gray)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_index -= 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.gray)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_index += 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

class WebhookBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=discord.Intents.default())
        self.web_app = web.Application()
        self.web_app.router.add_post('/webhook', self.handle_webhook)

    async def setup_hook(self):
        runner = web.AppRunner(self.web_app)
        await runner.setup()
        await web.TCPSite(runner, '0.0.0.0', WEBHOOK_PORT).start()

    async def handle_webhook(self, request: web.Request):
        # 1. 🔒 Security Check
        if request.headers.get('X-Webhook-Secret') != WEBHOOK_SECRET:
            return web.Response(text="Unauthorized", status=401)

        try:
            payload = await request.json()
            record = payload.get('record', {})
            user_id = record.get('user_id')
            
            # 2. 🔍 Fetch User Profile for "Mental Prep"
            profile = {"full_name": "Unknown", "avatar_url": None, "phone": "N/A"}
            async with aiohttp.ClientSession() as session:
                url = f"{SUPABASE_URL}/rest/v1/profiles?id=eq.{user_id}&select=*"
                headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
                async with session.get(url, headers=headers) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data: profile = data[0]

            channel = self.get_channel(TARGET_CHANNEL_ID)
            
            # 3. 📋 Detailed Briefing Embed
            price = f"{record.get('total_price', 0):,}".replace(',', ' ')
            briefing = discord.Embed(
                title=f"🆕 NEW REQUEST: {record.get('title', 'Untitled')}",
                description=f"👤 **Client:** {profile.get('full_name')}\n📞 **Phone:** {profile.get('phone', 'N/A')}\n💰 **Budget:** {price} FT",
                color=0xe67e22 if record.get('genre') == 'rnr' else 0x9b59b6
            )
            if profile.get('avatar_url'): briefing.set_thumbnail(url=profile.get('avatar_url'))
            briefing.add_field(name="🏷️ Genre", value=str(record.get('genre', 'N/A')).upper(), inline=True)
            briefing.add_field(name="⏱️ Target BPM", value=str(record.get('target_bpm', 'Var')), inline=True)
            briefing.add_field(name="📅 Deadline", value=record.get('deadline') or "ASAP", inline=False)

            # 4. 🔘 Buttons
            view = CarouselView(record.get('tracks', []))
            view.add_item(discord.ui.Button(label="📂 Admin Board", url="https://songtailor.vercel.app/admin", style=discord.ButtonStyle.link))
            view.add_item(discord.ui.Button(label="➕ New Request", url="https://songtailor.vercel.app/request", style=discord.ButtonStyle.link))

            await channel.send(embed=briefing)
            if record.get('tracks'): await channel.send(embed=view.get_embed(), view=view)

            return web.Response(text="OK", status=200)
        except Exception as e:
            logger.error(f"CRASH: {str(e)}")
            return web.Response(status=500)

if __name__ == "__main__":
    WebhookBot().run(TOKEN)