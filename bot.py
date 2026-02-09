import os
import json
import logging
import aiohttp
from typing import List
import discord
from discord.ext import commands
from aiohttp import web

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("DiscordWebhookBot")

# Variables from Railway
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
TARGET_CHANNEL_ID = int(os.getenv("TARGET_CHANNEL_ID"))
WEBHOOK_PORT = int(os.getenv("WEBHOOK_PORT", 8080))
WEBHOOK_SECRET = os.getenv("SUPABASE_JWT_SECRET")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

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
        track = self.tracks[self.current_index]
        embed = discord.Embed(
            title=f"🎼 Sneak Peak: {track.get('title', 'Untitled')}",
            url=track.get('url'),
            color=0x9b59b6
        )
        url = track.get('url', '')
        v_id = url.split('v=')[-1].split('&')[0] if 'v=' in url else url.split('/')[-1]
        embed.set_image(url=f"https://img.youtube.com/vi/{v_id}/mqdefault.jpg")
        embed.set_footer(text=f"Track {self.current_index + 1} of {len(self.tracks)}")
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
        # Added Intents to fix the warning in your logs
        intents = discord.Intents.default()
        intents.message_content = True 
        super().__init__(command_prefix="!", intents=intents)
        self.web_app = web.Application()
        self.web_app.router.add_post('/webhook', self.handle_webhook)

    async def setup_hook(self):
        runner = web.AppRunner(self.web_app)
        await runner.setup()
        await web.TCPSite(runner, '0.0.0.0', WEBHOOK_PORT).start()

    async def handle_webhook(self, request: web.Request):
        if request.headers.get('X-Webhook-Secret') != WEBHOOK_SECRET:
            return web.Response(text="Unauthorized", status=401)

        try:
            payload = await request.json()
            record = payload.get('record') or payload.get('new')
            
            # 🔍 Profile Lookup (Mental Prep)
            profile = {"full_name": "New Client"}
            async with aiohttp.ClientSession() as session:
                url = f"{SUPABASE_URL}/rest/v1/profiles?id=eq.{record.get('user_id')}&select=*"
                headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
                async with session.get(url, headers=headers) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data: profile = data[0]

            channel = await self.fetch_channel(TARGET_CHANNEL_ID)
            
            # 📋 Briefing Embed
            price = f"{int(record.get('total_price', 0)):,}".replace(',', ' ')
            briefing = discord.Embed(
                title=f"🚀 NEW REQUEST: {record.get('title', 'Untitled')}",
                description=f"👤 **Client:** {profile.get('full_name')}\n💰 **Budget:** {price} FT",
                color=15548997 if record.get('genre') == 'rnr' else 10181046
            )
            briefing.add_field(name="🏷️ Genre", value=str(record.get('genre')).upper(), inline=True)
            briefing.add_field(name="⏱️ BPM", value=str(record.get('target_bpm', 'Var')), inline=True)

            # 🔘 Action Buttons
            tracks = record.get('tracks', [])
            view = CarouselView(tracks) if tracks else discord.ui.View()
            view.add_item(discord.ui.Button(label="Open Admin Board", url="https://songtailor.vercel.app/admin", style=discord.ButtonStyle.link))

            await channel.send(embed=briefing)
            if tracks:
                await channel.send(embed=view.get_embed(), view=view)

            return web.Response(text="OK", status=200)
        except Exception as e:
            logger.error(f"CRASH: {e}")
            return web.Response(text=str(e), status=500)

if __name__ == "__main__":
    WebhookBot().run(TOKEN)