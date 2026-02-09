import os
import logging
import discord
import aiohttp
from discord.ext import commands
from aiohttp import web

# 1. Setup & Config
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("SongTailorBot")

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
TARGET_CHANNEL_ID = int(os.getenv("TARGET_CHANNEL_ID"))
WEBHOOK_PORT = int(os.getenv("WEBHOOK_PORT", 8080))
WEBHOOK_SECRET = os.getenv("SUPABASE_JWT_SECRET")

# Database Connection (For looking up names)
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

# 2. The Interactive Carousel
class CarouselView(discord.ui.View):
    def __init__(self, tracks, record):
        super().__init__(timeout=None)
        self.tracks = [t for t in tracks if t.get('url')]
        self.record = record
        self.current_index = 0
        self.update_buttons()

    def update_buttons(self):
        self.back_btn.disabled = (self.current_index == 0)
        self.next_btn.disabled = (self.current_index == len(self.tracks) - 1)

    def get_yt_image(self, url):
        if 'v=' in url: return f"https://img.youtube.com/vi/{url.split('v=')[-1].split('&')[0]}/mqdefault.jpg"
        if 'youtu.be/' in url: return f"https://img.youtube.com/vi/{url.split('youtu.be/')[-1].split('?')[0]}/mqdefault.jpg"
        return None

    def get_embed(self):
        track = self.tracks[self.current_index]
        color = 0xe67e22 if self.record.get('genre') == 'rnr' else 0x9b59b6
        
        embed = discord.Embed(
            title=f"🎵 Track {self.current_index + 1}: {track.get('title', 'Untitled')}",
            description=f"**[Click to Listen on YouTube]({track.get('url')})**",
            color=color
        )
        thumb_url = self.get_yt_image(track.get('url'))
        if thumb_url: embed.set_image(url=thumb_url)
        embed.set_footer(text=f"Preview {self.current_index + 1} of {len(self.tracks)} • {self.record.get('title')}")
        return embed

    @discord.ui.button(label="◀ Previous", style=discord.ButtonStyle.secondary)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_index -= 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_index += 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

# 3. Main Bot Logic
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

async def handle_webhook(request):
    if request.headers.get('X-Webhook-Secret') != WEBHOOK_SECRET:
        return web.Response(text="Unauthorized", status=401)

    try:
        data = await request.json()
        record = data.get('record', {})
        user_id = record.get('user_id')
        
        # --- 🔍 PROFILE LOOKUP START ---
        client_name = "Unknown Profile"
        
        if user_id and SUPABASE_URL and SUPABASE_KEY:
            try:
                async with aiohttp.ClientSession() as session:
                    url = f"{SUPABASE_URL}/rest/v1/profiles?id=eq.{user_id}&select=full_name"
                    headers = {
                        "apikey": SUPABASE_KEY,
                        "Authorization": f"Bearer {SUPABASE_KEY}"
                    }
                    async with session.get(url, headers=headers) as resp:
                        if resp.status == 200:
                            profiles = await resp.json()
                            if profiles and len(profiles) > 0:
                                client_name = profiles[0].get('full_name', 'Unknown')
            except Exception as e:
                logger.error(f"Could not fetch profile: {e}")
        # --- 🔍 PROFILE LOOKUP END ---

        channel = bot.get_channel(TARGET_CHANNEL_ID)
        if not channel: channel = await bot.fetch_channel(TARGET_CHANNEL_ID)

        # Briefing Embed
        price = f"{int(record.get('total_price', 0)):,}".replace(',', ' ')
        briefing = discord.Embed(
            title=f"🚀 NEW REQUEST: {record.get('title', 'Untitled')}",
            description=f"👤 **Profile:** {client_name}\n🆔 **User ID:** `{user_id}`\n💰 **Budget:** {price} FT",
            color=0xe67e22 if record.get('genre') == 'rnr' else 0x9b59b6
        )
        briefing.add_field(name="🏷️ Genre", value=str(record.get('genre', 'N/A')).upper(), inline=True)
        briefing.add_field(name="⏱️ BPM", value=str(record.get('target_bpm', 'Var')), inline=True)
        briefing.add_field(name="📅 Deadline", value=str(record.get('deadline', 'ASAP')), inline=False)
        
        # 🗑️ REMOVED: The mention line (<@...>) is gone.
        await channel.send(embed=briefing)

        # Carousel
        tracks = record.get('tracks', [])
        if tracks and len(tracks) > 0:
            view = CarouselView(tracks, record)
            view.add_item(discord.ui.Button(label="Open Admin Dashboard", url="https://song-tailor-website.vercel.app/pages/admin"))
            await channel.send(embed=view.get_embed(), view=view)
        
        return web.Response(text="OK", status=200)

    except Exception as e:
        logger.error(f"CRASH: {e}")
        return web.Response(text=f"Error: {e}", status=200)

async def setup_server():
    app = web.Application()
    app.router.add_post('/webhook', handle_webhook)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', WEBHOOK_PORT).start()

@bot.event
async def on_ready():
    logger.info(f"Bot Online: {bot.user}")
    await setup_server()

if __name__ == "__main__":
    bot.run(TOKEN)