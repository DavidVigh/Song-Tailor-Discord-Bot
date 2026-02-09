import os
import json
import hmac
import hashlib
import logging
import asyncio
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
WEBHOOK_PORT = int(os.getenv("WEBHOOK_PORT", 3000))  # Default to 3000 if not set
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET")

# Define Intents
intents = discord.Intents.default()
# Note: Message Content intent is not strictly necessary for just sending embeds/views
# but good to have if you expand functionality.
# intents.message_content = True

# --- Carousel View Logic ---

class CarouselView(discord.ui.View):
    """
    A View that manages an image carousel with Back and Next buttons.
    It maintains the state of which image index is currently being shown.
    """
    def __init__(self, images: List[str]):
        # timeout=None means the buttons won't stop working after X minutes.
        # Important: If the bot restarts, these views will stop working unless persistent views are implemented.
        super().__init__(timeout=None)
        self.images = images
        self.current_index = 0
        self.update_button_state()

    def update_button_state(self):
        """Enables/disables buttons based on current index position."""
        # Button children order: [0] is Back, [1] is Next
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
            # crucial: update the existing message with new embed and view state
            await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.primary, row=0)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_index < len(self.images) - 1:
            self.current_index += 1
            self.update_button_state()
            # crucial: update the existing message
            await interaction.response.edit_message(embed=self.get_embed(), view=self)


# --- Webhook Verification ---

def verify_supabase_signature(request_body: bytes, signature_header: str) -> bool:
    """
    Verifies that the request actually came from Supabase using the JWT secret.
    Supabase sends an 'x-supabase-signature' header containing the HMAC-SHA256 hex digest.
    """
    if not SUPABASE_JWT_SECRET or not signature_header:
        logger.warning("Missing JWT secret or signature header for verification.")
        return False

    # Create HMAC SHA256 using the secret key and the raw request body
    hmac_obj = hmac.new(
        key=SUPABASE_JWT_SECRET.encode('utf-8'),
        msg=request_body,
        digestmod=hashlib.sha256
    )
    calculated_signature = hmac_obj.hexdigest()
    
    # Securely compare the calculated signature with the header
    return hmac.compare_digest(calculated_signature, signature_header)


# --- Bot and Web Server Integration ---

class WebhookBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)
        self.web_app = web.Application()
        self.web_app.router.add_post('/webhook', self.handle_webhook)
        self.web_server_runner = None

    async def setup_hook(self):
        """Runs when the bot is starting up. We start the webserver here."""
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
        """Handles incoming POST requests from Supabase."""
        
        # 1. Read raw body for verification
        body_bytes = await request.read()
        signature_header = request.headers.get('x-supabase-signature')

        # 2. Verify Signature (Security Best Practice)
        # Comment this out if testing locally without real Supabase headers, 
        # but MUST enable in production.
        """ if not verify_supabase_signature(body_bytes, signature_header):
             logger.warning("Invalid webhook signature received.")
             return web.Response(text="Invalid Signature", status=401)
 """
        try:
            data = json.loads(body_bytes.decode('utf-8'))
            record = data.get('record', {})

            # 🛠️ FIX: Look into 'tracks' instead of 'thumbnail_urls'
            tracks = record.get('tracks', [])
            
            # Extract just the URLs from the track objects for the carousel
            thumbnail_urls = [t.get('url') for t in tracks if t.get('url')]

            if not thumbnail_urls:
                logger.warning("No track URLs found to display in carousel.")
                return web.Response(text="No tracks found", status=200)

            channel = self.get_channel(TARGET_CHANNEL_ID)
            if channel:
                view = CarouselView(thumbnail_urls)
                # You can customize this embed title to show the Project Title!
                embed = view.get_embed()
                embed.title = f"🎵 New Project: {record.get('title', 'Untitled')}"
                
                await channel.send(embed=embed, view=view)
                return web.Response(text="Carousel sent")

        except Exception as e:
            logger.error(f"Error: {e}")
            return web.Response(text="Internal Error", status=500)


if __name__ == "__main__":
    if not TOKEN or not TARGET_CHANNEL_ID or not SUPABASE_JWT_SECRET:
         logger.error("Missing necessary environment variables. Check .env file.")
         exit(1)

    bot = WebhookBot()
    bot.run(TOKEN)