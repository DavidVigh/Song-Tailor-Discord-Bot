import os
import json
import logging
import aiohttp
import discord
from discord.ext import commands
from aiohttp import web

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("DiscordWebhookBot")

# Load variables safely
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
TARGET_CHANNEL_ID = int(os.getenv("TARGET_CHANNEL_ID"))
WEBHOOK_PORT = int(os.getenv("WEBHOOK_PORT", 8080))
WEBHOOK_SECRET = os.getenv("SUPABASE_JWT_SECRET")

# --- Carousel View ---
class CarouselView(discord.ui.View):
    def __init__(self, tracks):
        super().__init__(timeout=None)
        self.tracks = [t for t in tracks if t.get('url')]
        self.current_index = 0

    def get_embed(self):
        track = self.tracks[self.current_index]
        embed = discord.Embed(title=f"🎼 Sneak Peak: {track.get('title', 'Untitled')}", color=0x9b59b6)
        embed.set_footer(text=f"Track {self.current_index + 1} of {len(self.tracks)}")
        return embed

# --- Bot Setup ---
class WebhookBot(commands.Bot):
    def __init__(self):
        # 🚨 FIX: Enable Intents to resolve log warnings
        intents = discord.Intents.default()
        intents.message_content = True 
        super().__init__(command_prefix="!", intents=intents)
        self.web_app = web.Application()
        self.web_app.router.add_post('/webhook', self.handle_webhook)

    async def setup_hook(self):
        runner = web.AppRunner(self.web_app)
        await runner.setup()
        await web.TCPSite(runner, '0.0.0.0', WEBHOOK_PORT).start()
        logger.info(f"Bot listening on port {WEBHOOK_PORT}")

    async def handle_webhook(self, request):
        if request.headers.get('X-Webhook-Secret') != WEBHOOK_SECRET:
            return web.Response(status=401)

        try:
            payload = await request.json()
            record = payload.get('record') or {}
            
            # 📢 Fetch Channel with Error Handling
            channel = self.get_channel(TARGET_CHANNEL_ID) or await self.fetch_channel(TARGET_CHANNEL_ID)
            
            # 📋 Briefing
            price = f"{int(record.get('total_price', 0)):,}".replace(',', ' ')
            briefing = discord.Embed(
                title=f"🚀 NEW REQUEST: {record.get('title', 'Untitled')}",
                description=f"💰 **Budget:** {price} FT",
                color=15548997 if record.get('genre') == 'rnr' else 10181046
            )

            # 🔘 Send Messages
            await channel.send(embed=briefing)
            return web.Response(text="OK", status=200)

        except Exception as e:
            # 🚨 Check "Deploy Logs" for this specific output!
            logger.error(f"WEBHOOK ERROR: {str(e)}")
            return web.Response(text=str(e), status=500)

if __name__ == "__main__":
    WebhookBot().run(TOKEN)