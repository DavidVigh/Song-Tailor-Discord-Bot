import os
import logging
import discord
from discord.ext import commands
from aiohttp import web

# 1. Setup & Config
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("SongTailorBot")

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
TARGET_CHANNEL_ID = int(os.getenv("TARGET_CHANNEL_ID"))
WEBHOOK_PORT = int(os.getenv("WEBHOOK_PORT", 8080))
WEBHOOK_SECRET = os.getenv("SUPABASE_JWT_SECRET")
ADMIN_USER_ID = os.getenv("ADMIN_USER_ID", 0) # Optional: Pings you

# 2. The Interactive Carousel
class CarouselView(discord.ui.View):
    def __init__(self, tracks, record):
        super().__init__(timeout=None) # Timeout=None means buttons never stop working
        self.tracks = [t for t in tracks if t.get('url')] # Filter empty links
        self.record = record
        self.current_index = 0
        self.update_buttons()

    def update_buttons(self):
        # Disable "Back" if we are on the first track
        self.back_btn.disabled = (self.current_index == 0)
        # Disable "Next" if we are on the last track
        self.next_btn.disabled = (self.current_index == len(self.tracks) - 1)

    def get_yt_image(self, url):
        # Extracts the ID from a YouTube URL to get the image
        if 'v=' in url: return f"https://img.youtube.com/vi/{url.split('v=')[-1].split('&')[0]}/mqdefault.jpg"
        if 'youtu.be/' in url: return f"https://img.youtube.com/vi/{url.split('youtu.be/')[-1].split('?')[0]}/mqdefault.jpg"
        return None

    def get_embed(self):
        track = self.tracks[self.current_index]
        
        # Color Logic: Orange for 'rnr', Purple for others
        color = 0xe67e22 if self.record.get('genre') == 'rnr' else 0x9b59b6
        
        embed = discord.Embed(
            title=f"🎵 Track {self.current_index + 1}: {track.get('title', 'Untitled')}",
            description=f"**[Click to Listen on YouTube]({track.get('url')})**",
            color=color
        )
        
        # Set the main image to the YouTube thumbnail
        thumb_url = self.get_yt_image(track.get('url'))
        if thumb_url: embed.set_image(url=thumb_url)
        
        # Footer shows progress (e.g., "Track 1 of 3")
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
        
        channel = bot.get_channel(TARGET_CHANNEL_ID)
        if not channel: channel = await bot.fetch_channel(TARGET_CHANNEL_ID)

        # A. The "Briefing" Embed (Top Card)
        price = f"{int(record.get('total_price', 0)):,}".replace(',', ' ')
        
        briefing = discord.Embed(
            title=f"🚀 NEW REQUEST: {record.get('title', 'Untitled')}",
            description=f"👤 **Profile:** {record.get('profile_name', 'Unknown')}\n🆔 **User ID:** `{record.get('user_id')}`\n💰 **Budget:** {price} FT",
            color=0xe67e22 if record.get('genre') == 'rnr' else 0x9b59b6
        )
        briefing.add_field(name="🏷️ Genre", value=str(record.get('genre', 'N/A')).upper(), inline=True)
        briefing.add_field(name="⏱️ BPM", value=str(record.get('target_bpm', 'Var')), inline=True)
        briefing.add_field(name="📅 Deadline", value=str(record.get('deadline', 'ASAP')), inline=False)
        
        await channel.send(embed=briefing)

        # B. The Carousel (Bottom Card)
        tracks = record.get('tracks', [])
        if tracks and len(tracks) > 0:
            view = CarouselView(tracks, record)
            
            # 👇 UPDATED LINK HERE 👇
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