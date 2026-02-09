import os
import json
import hmac
import hashlib
import logging
from typing import List

import discord
from discord.ext import commands
from dotenv import load_dotenv
from aiohttp import web

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("DiscordWebhookBot")

# Load environment variables
load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
TARGET_CHANNEL_ID = int(os.getenv("TARGET_CHANNEL_ID"))
WEBHOOK_PORT = int(os.getenv("WEBHOOK_PORT", 8080))
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET")

# Define Intents
intents = discord.Intents.default()

# --- Carousel View Logic ---

class CarouselView(discord.ui.View):
    """
    Manages an image carousel with Back and Next buttons.
    Maintains the state of which image index is currently being shown.
    """
    def __init__(self, images: List[str]):
        super().__init__(timeout=None)
        self.images = images
        self.current_index = 0
        self.update_button_state()

    def update_button_state(self):
        """Enables/disables buttons based on current index position."""
        self.back_button.disabled = (self.current_index == 0)
        self.next_button.disabled = (self.current_index == len(self.images) - 1)

    def get_embed(self) -> discord.Embed:
        """Generates the embed for the current index."""
        embed = discord.Embed(
            title=f"Image Gallery ({self.current_index + 1}/{len(self.images)})",
            color=discord.Color.blurple()
        )
        embed.set_image(url=self.images[self.current_index])
        embed.set_footer(text="Use buttons to navigate")
        return embed

    @discord.ui.button(label="◀ Back", style=discord.ButtonStyle.primary, row=0)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_index > 0:
            self.current_index -= 1
            self.update_button_state()
            await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.primary, row=0)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_index < len(self.images) - 1:
            self.current_index += 1
            self.update_button_state()
            await interaction.response.edit_message(embed=self.get_embed(), view=self)

# --- Webhook Verification ---

def verify_supabase_signature(request_body: bytes, signature_header: str) -> bool:
    """
    Verifies the HMAC-SHA256 signature from Supabase.
    """
    if not SUPABASE_JWT_SECRET:
        logger.error("SUPABASE_JWT_SECRET is missing in environment.")
        return False
    
    if not signature_header:
        logger.warning("No signature header found in incoming request.")
        return False

    hmac_obj = hmac.new(
        key=SUPABASE_JWT_SECRET.encode('utf-8'),
        msg=request_body,
        digestmod=hashlib.sha256
    )
    calculated_signature = hmac_obj.hexdigest()
    
    return hmac.compare_digest(calculated_signature, signature_header)

# --- Bot and Web Server Integration ---

class WebhookBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)
        self.web_app = web.Application()
        self.web_app.router.add_post('/webhook', self.handle_webhook)
        self.web_server_runner = None

    async def setup_hook(self):
        """Starts the aiohttp webserver when the bot launches."""
        self.web_server_runner = web.AppRunner(self.web_app)
        await self.web_server_runner.setup()
        site = web.TCPSite(self.web_server_runner, '0.0.0.0', WEBHOOK_PORT)
        await site.start()
        logger.info(f"Webhook server listening on 0.0.0.0:{WEBHOOK_PORT}/webhook")

    async def close(self):
        """Cleanup when bot shuts down."""
        await super().close()
        if self.web_server_runner:
            await self.web_server_runner.cleanup()

    async def on_ready(self):
        logger.info(f'Bot logged in as {self.user} (ID: {self.user.id})')

    async def handle_webhook(self, request: web.Request):
        """Processes incoming Supabase Webhooks."""
        body_bytes = await request.read()
        signature = request.headers.get('x-supabase-signature')

        # 🔒 Active Verification
        if not verify_supabase_signature(body_bytes, signature):
            logger.warning(f"Invalid signature received: {signature}")
            return web.Response(text="Unauthorized", status=401)

        try:
            data = json.loads(body_bytes.decode('utf-8'))
            record = data.get('record', {})

            # 🎵 Extract URLs from the 'tracks' JSONB column
            tracks = record.get('tracks', [])
            thumbnail_urls = [t.get('url') for t in tracks if t.get('url')]

            if not thumbnail_urls:
                logger.warning("No track URLs found in payload.")
                return web.Response(text="No tracks found", status=200)

            channel = self.get_channel(TARGET_CHANNEL_ID)
            if channel:
                view = CarouselView(thumbnail_urls)
                embed = view.get_embed()
                embed.title = f"🎵 New Project: {record.get('title', 'Untitled')}"
                
                await channel.send(embed=embed, view=view)
                return web.Response(text="Carousel sent", status=200)
            else:
                logger.error(f"Channel {TARGET_CHANNEL_ID} not found.")
                return web.Response(text="Channel not found", status=500)

        except Exception as e:
            logger.error(f"Error processing webhook: {e}")
            return web.Response(text="Internal Error", status=500)

if __name__ == "__main__":
    if not TOKEN or not TARGET_CHANNEL_ID or not SUPABASE_JWT_SECRET:
         logger.error("Missing environment variables. Check your Railway settings.")
         exit(1)

    bot = WebhookBot()
    bot.run(TOKEN)