import os
import json
import logging
import aiohttp
from typing import List

import discord
from discord.ext import commands
from aiohttp import web

# Logging is your best friend now - check "Deploy Logs" in Railway
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("DiscordWebhookBot")

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
TARGET_CHANNEL_ID = int(os.getenv("TARGET_CHANNEL_ID"))
WEBHOOK_PORT = int(os.getenv("WEBHOOK_PORT", 8080))
WEBHOOK_SECRET = os.getenv("SUPABASE_JWT_SECRET")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

class CarouselView(discord.ui.View):
    def __init__(self, tracks: List[dict]):
        super().__init__(timeout=None)
        # Filter for tracks that have a URL to prevent empty embed crashes
        self.tracks = [t for t in tracks if t and t.get('url')]
        self.current_index = 0
        self.update_buttons()

    def update_buttons(self):
        if not self.tracks: return
        self.back_btn.disabled = (self.current_index == 0)
        self.next_btn.disabled = (self.current_index == len(self.tracks) - 1)

    def get_embed(self) -> discord.Embed:
        if not self.tracks:
            return discord.Embed(title="⚠️ No valid track links provided", color=discord.Color.red())
            
        track = self.tracks[self.current_index]
        embed = discord.Embed(
            title=f"🎼 Track Preview: {track.get('title', 'Untitled')}",
            url=track.get('url'),
            color=0x9b59b6
        )
        
        # Robust YouTube ID extractor
        url = str(track.get('url', ''))
        v_id = None
        if 'v=' in url:
            v_id = url.split('v=')[-1].split('&')[0]
        elif 'youtu.be/' in url:
            v_id = url.split('youtu.be/')[-1].split('?')[0]
            
        if v_id:
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
        logger.info(f"Bot listening on port {WEBHOOK_PORT}")

    async def handle_webhook(self, request: web.Request):
        # 🔒 Security check
        if request.headers.get('X-Webhook-Secret') != WEBHOOK_SECRET:
            return web.Response(text="Unauthorized", status=401)

        try:
            payload = await request.json()
            record = payload.get('record', {})
            user_id = record.get('user_id')
            
            # 🔍 Attempt User Profile Lookup
            profile = {"full_name": "New Client", "avatar_url": None}
            if SUPABASE_URL and SUPABASE_KEY and user_id:
                async with aiohttp.ClientSession() as session:
                    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
                    async with session.get(f"{SUPABASE_URL}/rest/v1/profiles?id=eq.{user_id}&select=*", headers=headers) as resp:
                        if resp.status == 200:
                            p_data = await resp.json()
                            if p_data: profile = p_data[0]

            # 📢 Discord Channel Check (Fixes the most common 500 error)
            channel = self.get_channel(TARGET_CHANNEL_ID)
            if not channel:
                logger.info(f"Channel {TARGET_CHANNEL_ID} not in cache, fetching...")
                try:
                    channel = await self.fetch_channel(TARGET_CHANNEL_ID)
                except Exception as e:
                    logger.error(f"CRITICAL: Bot cannot access channel {TARGET_CHANNEL_ID}: {e}")
                    return web.Response(text="Channel Access Error", status=500)

            # 📋 Briefing Construction
            price_val = record.get('total_price') or 0
            price_str = f"{int(price_val):,}".replace(',', ' ')
            
            briefing = discord.Embed(
                title=f"🚀 NEW REQUEST: {record.get('title', 'Untitled')}",
                description=f"👤 **Client:** {profile.get('full_name')}\n💰 **Budget:** {price_str} FT",
                color=0xe67e22 if record.get('genre') == 'rnr' else 0x9b59b6
            )
            if profile.get('avatar_url'): briefing.set_thumbnail(url=profile.get('avatar_url'))
            
            briefing.add_field(name="🏷️ Genre", value=str(record.get('genre', 'N/A')).upper(), inline=True)
            briefing.add_field(name="⏱️ BPM", value=str(record.get('target_bpm', 'Var')), inline=True)
            briefing.add_field(name="📅 Deadline", value=str(record.get('deadline') or "ASAP"), inline=False)

            # 🔘 Action View
            tracks = record.get('tracks', [])
            view = CarouselView(tracks) if tracks else discord.ui.View()
            view.add_item(discord.ui.Button(label="Open Admin Board", url="https://songtailor.vercel.app/admin", style=discord.ButtonStyle.link))
            view.add_item(discord.ui.Button(label="New Request", url="https://songtailor.vercel.app/request", style=discord.ButtonStyle.link))

            # Send the data
            await channel.send(embed=briefing)
            if tracks:
                carousel_embed = view.get_embed()
                if "No valid track links" not in str(carousel_embed.title):
                    await channel.send(embed=carousel_embed, view=view)

            return web.Response(text="OK", status=200)

        except Exception as e:
            # 💡 This is the secret to fixing the 500: Check your Railway "Deploy Logs"!
            logger.error(f"WEBHOOK PROCESSING FAILED: {str(e)}")
            return web.Response(text=str(e), status=500)

if __name__ == "__main__":
    WebhookBot().run(TOKEN)