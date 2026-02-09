import os
import json
import logging
import aiohttp
import discord
from discord.ext import commands
from aiohttp import web

# 1. Setup Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("DebugBot")

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
TARGET_CHANNEL_ID = int(os.getenv("TARGET_CHANNEL_ID"))
WEBHOOK_PORT = int(os.getenv("WEBHOOK_PORT", 8080))
WEBHOOK_SECRET = os.getenv("SUPABASE_JWT_SECRET")

# 2. Minimal Bot Setup (Intents Enabled)
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

async def handle_webhook(request):
    # 3. Security Check
    secret = request.headers.get('X-Webhook-Secret')
    if secret != WEBHOOK_SECRET:
        logger.warning(f"Security Mismatch! Expected {WEBHOOK_SECRET}, got {secret}")
        return web.Response(text="Bad Secret", status=401)

    try:
        # 4. Try to parse data
        data = await request.json()
        record = data.get('record', {})
        logger.info(f"Payload received for: {record.get('title', 'Unknown')}")

        # 5. Try to find channel
        channel = bot.get_channel(TARGET_CHANNEL_ID)
        if not channel:
            logger.info("Channel not in cache, fetching...")
            try:
                channel = await bot.fetch_channel(TARGET_CHANNEL_ID)
            except Exception as ex:
                return web.Response(text=f"ERROR: Cannot find channel. {ex}", status=200)

        # 6. Try to send a simple message first
        try:
            # We skip the complex embed for 1 second to test the connection
            await channel.send(f"✅ **Connection Successful!**\nNew Project: {record.get('title', 'Untitled')}")
        except Exception as ex:
            return web.Response(text=f"ERROR: Cannot send message. Permissions? {ex}", status=200)

        # If we get here, it worked!
        return web.Response(text="Success!", status=200)

    except Exception as e:
        # 🚨 THIS IS THE MAGIC FIX 🚨
        # Instead of crashing with 500, we return 200 and print the error.
        logger.error(f"CRASH: {e}")
        return web.Response(text=f"Handled Error: {e}", status=200)

async def setup_server():
    app = web.Application()
    app.router.add_post('/webhook', handle_webhook)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', WEBHOOK_PORT)
    await site.start()
    logger.info(f"Server running on port {WEBHOOK_PORT}")

@bot.event
async def on_ready():
    logger.info(f"Logged in as {bot.user}")
    await setup_server()

if __name__ == "__main__":
    bot.run(TOKEN)