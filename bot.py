import os
import json
import logging
from typing import List

import discord
from discord.ext import commands
from dotenv import load_dotenv
from aiohttp import web

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("DiscordWebhookBot")

load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
TARGET_CHANNEL_ID = int(os.getenv("TARGET_CHANNEL_ID"))
WEBHOOK_PORT = int(os.getenv("WEBHOOK_PORT", 8080))
# 🔑 Use this as your shared secret!
WEBHOOK_SECRET = os.getenv("SUPABASE_JWT_SECRET")

intents = discord.Intents.default()

class CarouselView(discord.ui.View):
    def __init__(self, tracks: List[dict]):
        super().__init__(timeout=None)
        self.tracks = tracks
        self.current_index = 0
        self.update_buttons()

    def update_buttons(self):
        self.back_btn.disabled = (self.current_index == 0)
        self.next_btn.disabled = (self.current_index == len(self.tracks) - 1)

    def get_embed(self) -> discord.Embed:
        track = self.tracks[self.current_index]
        embed = discord.Embed(
            title=f"🎵 Track {self.current_index + 1}: {track.get('title', 'Untitled')}",
            url=track.get('url'),
            color=0x9b59b6 # Purple
        )
        # YouTube Thumbnail logic
        video_id = track.get('url', '').split('v=')[-1] if 'v=' in track.get('url', '') else None
        if video_id:
            embed.set_image(url=f"https://img.youtube.com/vi/{video_id}/mqdefault.jpg")
        
        embed.set_footer(text=f"Navigate tracks ({self.current_index + 1}/{len(self.tracks)})")
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
        super().__init__(command_prefix="!", intents=intents)
        self.web_app = web.Application()
        self.web_app.router.add_post('/webhook', self.handle_webhook)

    async def setup_hook(self):
        runner = web.AppRunner(self.web_app)
        await runner.setup()
        await web.TCPSite(runner, '0.0.0.0', WEBHOOK_PORT).start()
        logger.info(f"Server ready on port {WEBHOOK_PORT}")

    async def handle_webhook(self, request: web.Request):
        # 🔒 SECURE VERIFICATION
        received_secret = request.headers.get('X-Webhook-Secret')
        if received_secret != WEBHOOK_SECRET:
            logger.warning("Unauthorized access attempt (401)")
            return web.Response(text="Unauthorized", status=401)

        try:
            payload = await request.json()
            record = payload.get('record', {})
            tracks = record.get('tracks', [])
            
            channel = self.get_channel(TARGET_CHANNEL_ID)
            if not channel: return web.Response(status=500)

            # 📋 Project Briefing Embed
            price = f"{record.get('total_price', 0):,}".replace(',', ' ')
            briefing = discord.Embed(
                title=f"🚀 NEW PROJECT: {record.get('title', 'Untitled')}",
                description=f"**Service:** {record.get('service_name', 'N/A')}\n**Budget:** {price} FT",
                color=0xe67e22 if record.get('genre') == 'rnr' else 0x9b59b6
            )
            briefing.add_field(name="🏷️ Genre", value=record.get('genre', 'N/A').upper(), inline=True)
            briefing.add_field(name="⏱️ BPM", value=record.get('target_bpm', 'Var'), inline=True)
            briefing.add_field(name="📅 Deadline", value=record.get('deadline') or "ASAP", inline=False)

            # 🔘 Buttons
            view = CarouselView(tracks) if tracks else discord.ui.View()
            view.add_item(discord.ui.Button(label="Open Admin Board", url="https://song-tailor.vercel.app/admin", style=discord.ButtonStyle.link))
            view.add_item(discord.ui.Button(label="New Request", url="https://song-tailor.vercel.app/request", style=discord.ButtonStyle.link))

            await channel.send(embed=briefing)
            if tracks:
                await channel.send(embed=view.get_embed(), view=view)

            return web.Response(text="OK", status=200)
        except Exception as e:
            logger.error(f"Error: {e}")
            return web.Response(status=500)

if __name__ == "__main__":
    WebhookBot().run(TOKEN)