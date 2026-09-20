
"""
Japablueprint.com.ng Professional AI Bot
- Talks like Meta AI (Gemini 1.5 Flash brain)
- Auto-posts latest articles 4x/week to Telegram channel
- Commands: /start /latest /post /ask
- Ready for Render FREE Web Service
"""

import os
import json
import logging
import requests
import asyncio
from datetime import datetime
from bs4 import BeautifulSoup
from flask import Flask, request
import google.generativeai as genai
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # https://your-app.onrender.com/webhook
CHANNEL_ID = os.getenv("CHANNEL_ID")  # @japablueprint or -100xxxx
WEBSITE = "https://japablueprint.com.ng"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# AI Brain - safe init
try:
    if GEMINI_API_KEY:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel("gemini-1.5-flash")
    else:
        model = None
except Exception as e:
    print(f"Gemini init failed: {e}")
    model = None

# Timezone for Nigeria
LAGOS_TZ = pytz.timezone("Africa/Lagos")
POSTED_FILE = "posted.json"

# --- WEBSITE SCRAPER ---
def get_all_latest(limit=10):
    """Get latest posts from site"""
    try:
        r = requests.get(f"{WEBSITE}/feed/", timeout=15, headers={"User-Agent":"Mozilla/5.0"})
        if "<item>" in r.text:
            soup = BeautifulSoup(r.text, "xml")
            items = soup.find_all("item")[:limit]
            posts = []
            for it in items:
                title = it.title.text.strip() if it.title else ""
                link = it.link.text.strip() if it.link else ""
                desc = it.description.text[:200] if it.description else ""
                if title and link:
                    posts.append({"title": title, "link": link, "desc": desc})
            if posts:
                return posts
    except Exception as e:
        logger.error(f"RSS error: {e}")

    # Fallback: scrape homepage
    try:
        r = requests.get(WEBSITE, timeout=15, headers={"User-Agent":"Mozilla/5.0"})
        soup = BeautifulSoup(r.text, "html.parser")
        posts=[]
        for a in soup.select("h2 a, h3.entry-title a, .post-title a")[:limit]:
            title = a.get_text(strip=True)
            href = a.get("href")
            if title and href and "/202" in href or len(title)>10:
                posts.append({"title": title, "link": href, "desc": ""})
        return posts[:limit]
    except Exception as e:
        logger.error(f"Scrape error: {e}")
    return []

def get_latest_formatted(limit=3):
    posts = get_all_latest(limit)
    if not posts:
        return f"Visit latest guides 👉 {WEBSITE}/blog/"
    msg = "🔥 Latest from Japablueprint.com.ng:\n\n"
    for i, p in enumerate(posts, 1):
        msg += f"{i}. {p['title']}\n{p['link']}\n\n"
    msg += f"📚 More guides: {WEBSITE}"
    return msg

def get_next_unposted():
    """Get one new post that hasn't been auto-posted before"""
    posts = get_all_latest(10)
    if not posts:
        return None
    # Load posted history
    posted = []
    if os.path.exists(POSTED_FILE):
        try:
            with open(POSTED_FILE, "r") as f:
                posted = json.load(f)
        except:
            posted = []
    for p in posts:
        if p["link"] not in posted:
            return p
    # If all posted, return newest anyway (for 4x/week we still post)
    return posts[0] if posts else None

def mark_as_posted(link):
    posted=[]
    if os.path.exists(POSTED_FILE):
        try:
            with open(POSTED_FILE, "r") as f:
                posted=json.load(f)
        except:
            posted=[]
    if link not in posted:
        posted.append(link)
        # Keep only last 100
        posted = posted[-100:]
        with open(POSTED_FILE, "w") as f:
            json.dump(posted, f)

def send_to_channel_direct(text):
    """Send via direct HTTP - works from background scheduler thread"""
    if not CHANNEL_ID or not BOT_TOKEN:
        logger.error("CHANNEL_ID or BOT_TOKEN missing for auto-post")
        return False
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {"chat_id": CHANNEL_ID, "text": text, "parse_mode": "HTML", "disable_web_page_preview": False}
        r = requests.post(url, json=payload, timeout=15)
        logger.info(f"Auto-post to {CHANNEL_ID}: {r.text}")
        return r.status_code == 200
    except Exception as e:
        logger.error(f"Auto-post failed: {e}")
        return False

def auto_post_job():
    """Runs 4x a week - posts latest article to channel"""
    logger.info(f"Auto-post job triggered at {datetime.now(LAGOS_TZ)}")
    post = get_next_unposted()
    if not post:
        logger.info("No new post to auto-post")
        return
    # Professional formatted post
    caption = f"🇯🇵 <b>{post['title']}</b>\n\n{post['desc'][:250]}...\n\n👉 Read full guide: {post['link']}\n\n#Japa #Travel #Japan #SwedenPOF #Canada #UKVisa #Japablueprint"
    # Clean HTML
    caption = caption.replace("<b>", "<b>").replace("</b>", "</b>")  # keep bold
    if send_to_channel_direct(caption):
        mark_as_posted(post["link"])
        logger.info(f"Auto-posted: {post['title']}")

def ask_ai(question: str) -> str:
    if not model:
        return f"AI key not set. Visit {WEBSITE} for guides - search your topic there. 🛫"
    try:
        prompt = f"""
You are Japablueprint.com.ng Professional Travel AI - like Meta AI.

ABOUT YOU:
- You are the official AI assistant for Japablueprint.com.ng
- Website {WEBSITE} is Nigeria's #1 Japa, travel, visa, POF, jobs abroad guide
- Expert in: Japan visa/process, Sweden POF 103140 SEK (2025), Canada, UK, USA, Schengen, Australia, Germany, Proof of Funds, Bank Statements, Jobs Abroad, Scholarships

STYLE:
- Talk exactly like Meta AI - friendly, conversational, helpful
- Use bullet points, emojis sparingly, clear steps
- Give 2025 updated, accurate info
- Keep answers under 350 words unless detailed guide needed
- If question is about Sweden POF, mention 103140 SEK for 2025
- Always end with: "📚 Full guide: {WEBSITE} - Search your topic there"

User question: {question}

Answer helpfully:
"""
        resp = model.generate_content(prompt)
        return resp.text
    except Exception as e:
        logger.error(f"Gemini error: {e}")
        return f"I'm having a small issue with my AI brain now. Please visit {WEBSITE} and search your topic - all guides are there. Or ask again in 10 seconds. 🛫"

# --- TELEGRAM HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🇯🇵 <b>Japablueprint AI is Online!</b>\n\n"
        "I talk just like Meta AI, but I'm trained on Japablueprint.com.ng travel guides!\n\n"
        "<b>Ask me anything:</b>\n"
        "• What is Sweden POF 103140 SEK?\n"
        "• Japan student visa for Nigerians\n"
        "• How to Japa to Canada 2025\n"
        "• POF for UK, USA, Schengen\n\n"
        "<b>Commands:</b>\n"
        "/latest - 3 latest posts\n"
        "/latest @channel - post latest to channel\n"
        "/post @channel Your message - manual post\n"
        "/ask Your question - ask AI\n\n"
        "I also auto-post new guides to channel 4x a week! 🚀\n\n"
        f"📚 Website: {WEBSITE}",
        parse_mode="HTML"
    )

async def latest_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    channel = None
    if context.args and (context.args[0].startswith("@") or context.args[0].startswith("-100")):
        channel = context.args[0]
    text = get_latest_formatted(3)
    if channel:
        try:
            await context.bot.send_message(chat_id=channel, text=text, parse_mode="HTML")
            await update.message.reply_text(f"✅ Posted latest to {channel}")
        except Exception as e:
            await update.message.reply_text(f"❌ Make me ADMIN in {channel} with 'Post Messages' right.\nError: {e}")
    else:
        await update.message.reply_text(text, parse_mode="HTML")

async def post_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or len(context.args)<2:
        await update.message.reply_text("Use: /post @japablueprint Your message here")
        return
    channel = context.args[0]
    msg = " ".join(context.args[1:])
    try:
        await context.bot.send_message(chat_id=channel, text=msg, parse_mode="HTML")
        await update.message.reply_text(f"✅ Posted to {channel}")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed. Make me ADMIN in {channel}.\nError: {e}")

async def ask_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    question = " ".join(context.args) if context.args else ""
    if not question:
        await update.message.reply_text("Use: /ask What is Sweden POF?")
        return
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    ans = ask_ai(question)
    await update.message.reply_text(ans)

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text.startswith("/"):
        return
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    ans = ask_ai(update.message.text)
    await update.message.reply_text(ans)

# Build Telegram app - safe
if not BOT_TOKEN:
    print("ERROR: BOT_TOKEN not set!")
    BOT_TOKEN = "dummy"
application = Application.builder().token(BOT_TOKEN).build()
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("latest", latest_cmd))
application.add_handler(CommandHandler("post", post_cmd))
application.add_handler(CommandHandler("ask", ask_cmd))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

# Flask for Render FREE web service
flask_app = Flask(__name__)

@flask_app.route("/")
def home():
    return f"Japablueprint Bot Running ✅ - Last check: {datetime.now(LAGOS_TZ)} - Auto-posts 4x/week to {CHANNEL_ID}"

@flask_app.route("/health")
def health():
    return "OK"

@flask_app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json(force=True)
        async def process():
            update = Update.de_json(data, application.bot)
            await application.process_update(update)
        asyncio.run(process())
    except Exception as e:
        logger.error(f"Webhook error: {e}")
    return "OK"

# --- SCHEDULER: 4x a week auto-post ---
# Monday, Tuesday, Thursday, Saturday at 9:00 AM Lagos time (8:00 AM UTC)
scheduler = BackgroundScheduler(timezone=str(LAGOS_TZ))
scheduler.add_job(auto_post_job, CronTrigger(day_of_week="mon", hour=9, minute=0, timezone=LAGOS_TZ), id="mon_post")
scheduler.add_job(auto_post_job, CronTrigger(day_of_week="tue", hour=9, minute=0, timezone=LAGOS_TZ), id="tue_post")
scheduler.add_job(auto_post_job, CronTrigger(day_of_week="thu", hour=9, minute=0, timezone=LAGOS_TZ), id="thu_post")
scheduler.add_job(auto_post_job, CronTrigger(day_of_week="sat", hour=9, minute=0, timezone=LAGOS_TZ), id="sat_post")
# Also test job every 6 hours to catch new posts if missed (optional, comment out if not needed)
# scheduler.add_job(auto_post_job, 'interval', hours=24, id="daily_check")

def start_scheduler():
    try:
        if not scheduler.running:
            scheduler.start()
            logger.info("Scheduler started - Auto-post Mon, Tue, Thu, Sat 9AM WAT")
    except Exception as e:
        logger.error(f"Scheduler error: {e}")

if __name__ == "__main__":
    start_scheduler()
    if WEBHOOK_URL:
        # Webhook mode for Render FREE
        try:
            # Set webhook
            requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook?url={WEBHOOK_URL}", timeout=10)
            logger.info(f"Webhook set to {WEBHOOK_URL}")
        except Exception as e:
            logger.error(f"Set webhook failed: {e}")
        port = int(os.environ.get("PORT", 10000))
        logger.info(f"Starting Flask on port {port}")
        flask_app.run(host="0.0.0.0", port=port)
    else:
        # Polling for local testing
        logger.info("Running in polling mode (local)")
        application.run_polling()
