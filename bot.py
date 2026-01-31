#!/usr/bin/env python3
"""
OLX.uz kvartira e'lonlarini kuzatuvchi Telegram Mini App bot.
"""

import os
import json
import re
import sqlite3
import threading
import time
import logging
from typing import Optional, List
from contextlib import contextmanager

import requests
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Environment variables
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
WEBAPP_URL = os.environ.get("WEBAPP_URL", "")  # Mini App URL

# Constants
BASE_URL = "https://www.olx.uz"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
CHECK_INTERVAL = 60
DB_PATH = "olx_bot.db"

app = Flask(__name__, static_folder='webapp')
CORS(app)


# ============== Database ==============

@contextmanager
def get_db():
    """Database connection context manager."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    """Initialize database."""
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS seen_listings (
                listing_id TEXT PRIMARY KEY,
                title TEXT,
                price TEXT,
                url TEXT,
                first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS filter_urls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id TEXT NOT NULL,
                url TEXT NOT NULL,
                name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(chat_id, url)
            )
        """)
        conn.commit()


def add_filter(chat_id: str, url: str, name: str = None) -> dict:
    """Add new filter URL."""
    try:
        with get_db() as conn:
            cursor = conn.execute(
                "INSERT INTO filter_urls (chat_id, url, name) VALUES (?, ?, ?)",
                (chat_id, url, name)
            )
            conn.commit()
            return {"success": True, "id": cursor.lastrowid}
    except sqlite3.IntegrityError:
        return {"success": False, "error": "Bu filter allaqachon qo'shilgan"}


def remove_filter(chat_id: str, filter_id: int) -> bool:
    """Remove filter URL."""
    with get_db() as conn:
        cursor = conn.execute(
            "DELETE FROM filter_urls WHERE id = ? AND chat_id = ?",
            (filter_id, chat_id)
        )
        conn.commit()
        return cursor.rowcount > 0


def get_filters(chat_id: str) -> List[dict]:
    """Get all filters for chat."""
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT id, url, name, created_at FROM filter_urls WHERE chat_id = ? ORDER BY id DESC",
            (chat_id,)
        )
        return [dict(row) for row in cursor.fetchall()]


def get_all_filters() -> List[dict]:
    """Get all filters."""
    with get_db() as conn:
        cursor = conn.execute("SELECT chat_id, url FROM filter_urls")
        return [dict(row) for row in cursor.fetchall()]


def is_seen(listing_id: str) -> bool:
    """Check if listing was seen."""
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT 1 FROM seen_listings WHERE listing_id = ?",
            (listing_id,)
        )
        return cursor.fetchone() is not None


def mark_seen(listing_id: str, title: str, price: str, url: str):
    """Mark listing as seen."""
    with get_db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO seen_listings (listing_id, title, price, url) VALUES (?, ?, ?, ?)",
            (listing_id, title, price, url)
        )
        conn.commit()


# ============== OLX Scraper ==============

class OLXScraper:
    """OLX.uz scraper."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})

    def extract_listing_id(self, url: str) -> Optional[str]:
        """Extract listing ID from URL."""
        match = re.search(r'-ID([a-zA-Z0-9]+)\.html', url)
        return match.group(1) if match else None

    def fetch_listings(self, filter_url: str) -> list:
        """Fetch listings from OLX."""
        from bs4 import BeautifulSoup

        try:
            response = self.session.get(filter_url, timeout=30)
            response.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"OLX error: {e}")
            return []

        soup = BeautifulSoup(response.text, 'html.parser')
        listings = []

        cards = soup.select('[data-cy="l-card"]') or soup.select('.offer-wrapper')

        for card in cards:
            try:
                link_elem = card.select_one('a[href*="/d/"]')
                if not link_elem:
                    continue

                href = link_elem.get('href', '')
                if not href.startswith('http'):
                    href = BASE_URL + href

                listing_id = self.extract_listing_id(href)
                if not listing_id:
                    continue

                title_elem = card.select_one('h6')
                title = title_elem.get_text(strip=True) if title_elem else "Sarlavhasiz"

                price_elem = card.select_one('[data-testid="ad-price"]')
                price = price_elem.get_text(strip=True) if price_elem else "Narx ko'rsatilmagan"

                location_elem = card.select_one('[data-testid="location-date"]')
                location = location_elem.get_text(strip=True) if location_elem else ""

                listings.append({
                    "id": listing_id,
                    "title": title,
                    "price": price,
                    "url": href,
                    "location": location
                })
            except Exception as e:
                logger.warning(f"Parse error: {e}")

        return listings


scraper = OLXScraper()


# ============== Telegram ==============

def send_telegram(chat_id: str, text: str, reply_markup: dict = None) -> bool:
    """Send Telegram message."""
    try:
        data = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False
        }
        if reply_markup:
            data["reply_markup"] = reply_markup

        response = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json=data,
            timeout=30
        )
        return response.ok
    except Exception as e:
        logger.error(f"Telegram error: {e}")
        return False


def get_webapp_button():
    """Get Mini App button."""
    return {
        "inline_keyboard": [[{
            "text": "🏠 Filterlarni boshqarish",
            "web_app": {"url": WEBAPP_URL}
        }]]
    }


# ============== API Routes ==============

@app.route('/')
def index():
    """Serve Mini App."""
    return send_from_directory('webapp', 'index.html')


@app.route('/<path:path>')
def serve_static(path):
    """Serve static files."""
    return send_from_directory('webapp', path)


@app.route('/api/filters', methods=['GET'])
def api_get_filters():
    """Get filters for user."""
    chat_id = request.args.get('chat_id')
    if not chat_id:
        return jsonify({"error": "chat_id required"}), 400

    filters = get_filters(chat_id)
    return jsonify({"filters": filters})


@app.route('/api/filters', methods=['POST'])
def api_add_filter():
    """Add new filter."""
    data = request.json
    chat_id = data.get('chat_id')
    url = data.get('url')
    name = data.get('name')

    if not chat_id or not url:
        return jsonify({"error": "chat_id and url required"}), 400

    if not url.startswith("https://www.olx.uz"):
        return jsonify({"error": "Faqat OLX.uz havolalari qabul qilinadi"}), 400

    result = add_filter(chat_id, url, name)

    if result["success"]:
        # Mark existing listings as seen
        listings = scraper.fetch_listings(url)
        for listing in listings:
            mark_seen(listing['id'], listing['title'], listing['price'], listing['url'])

    return jsonify(result)


@app.route('/api/filters/<int:filter_id>', methods=['DELETE'])
def api_remove_filter(filter_id):
    """Remove filter."""
    chat_id = request.args.get('chat_id')
    if not chat_id:
        return jsonify({"error": "chat_id required"}), 400

    success = remove_filter(chat_id, filter_id)
    return jsonify({"success": success})


@app.route('/webhook', methods=['POST'])
def webhook():
    """Telegram webhook handler."""
    data = request.json

    if 'message' in data:
        message = data['message']
        chat_id = str(message['chat']['id'])
        text = message.get('text', '')

        if text == '/start':
            send_telegram(
                chat_id,
                "🏠 <b>OLX Kvartira Kuzatuvchi</b>\n\n"
                "Men OLX.uz'dagi kvartira e'lonlarini kuzataman.\n\n"
                "Quyidagi tugmani bosib, filterlarni boshqaring:",
                get_webapp_button()
            )
        elif text == '/help':
            send_telegram(
                chat_id,
                "📖 <b>Yordam</b>\n\n"
                "1. Tugmani bosing va Mini App'ni oching\n"
                "2. OLX.uz dan filter URL'ini qo'shing\n"
                "3. Yangi e'lonlar haqida avtomatik xabar olasiz\n\n"
                "Har 1 daqiqada tekshiriladi.",
                get_webapp_button()
            )
        elif text == '/filters':
            send_telegram(chat_id, "Filterlarni ko'rish uchun:", get_webapp_button())
        else:
            send_telegram(
                chat_id,
                "Filterlarni boshqarish uchun quyidagi tugmani bosing:",
                get_webapp_button()
            )

    return jsonify({"ok": True})


# ============== Background Checker ==============

def check_all_urls():
    """Check all URLs for new listings."""
    filters = get_all_filters()

    chat_urls = {}
    for f in filters:
        chat_id = f['chat_id']
        if chat_id not in chat_urls:
            chat_urls[chat_id] = []
        chat_urls[chat_id].append(f['url'])

    for chat_id, urls in chat_urls.items():
        for url in urls:
            try:
                listings = scraper.fetch_listings(url)
                for listing in listings:
                    if not is_seen(listing['id']):
                        message = (
                            f"🏠 <b>Yangi e'lon!</b>\n\n"
                            f"<b>{listing['title']}</b>\n\n"
                            f"💰 {listing['price']}\n"
                            f"📍 {listing['location']}\n\n"
                            f"🔗 <a href=\"{listing['url']}\">E'lonni ko'rish</a>"
                        )
                        send_telegram(chat_id, message)
                        mark_seen(listing['id'], listing['title'], listing['price'], listing['url'])
                        time.sleep(0.5)
            except Exception as e:
                logger.error(f"Check error: {e}")
            time.sleep(1)


def checker_loop():
    """Background checker loop."""
    logger.info("Checker started")
    while True:
        try:
            check_all_urls()
        except Exception as e:
            logger.error(f"Checker error: {e}")
        time.sleep(CHECK_INTERVAL)


# ============== Main ==============

def setup_webhook():
    """Setup Telegram webhook."""
    if BOT_TOKEN and WEBAPP_URL:
        webhook_url = WEBAPP_URL.rstrip('/') + '/webhook'
        try:
            response = requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook",
                json={"url": webhook_url}
            )
            logger.info(f"Webhook setup: {response.json()}")
        except Exception as e:
            logger.error(f"Webhook setup error: {e}")


if __name__ == '__main__':
    init_db()
    setup_webhook()

    # Start background checker
    checker_thread = threading.Thread(target=checker_loop, daemon=True)
    checker_thread.start()

    # Run Flask
    app.run(host='0.0.0.0', port=8000)
