#!/usr/bin/env python3
"""
OLX.uz e'lonlarini kuzatuvchi Telegram bot.
Polling mode - HTTPS talab qilmaydi.
"""

import os
import re
import json
import sqlite3
import threading
import time
import logging
from typing import Optional, List
from contextlib import contextmanager

import requests
from bs4 import BeautifulSoup

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Environment variables
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")

# Constants
BASE_URL = "https://www.olx.uz"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
CHECK_INTERVAL = 60
DB_PATH = "/opt/olx-bot/olx_bot.db"


# ============== Database ==============

@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_db():
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
    logger.info("Database initialized")


def add_filter(chat_id: str, url: str, name: str = None) -> dict:
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
    with get_db() as conn:
        cursor = conn.execute(
            "DELETE FROM filter_urls WHERE id = ? AND chat_id = ?",
            (filter_id, chat_id)
        )
        conn.commit()
        return cursor.rowcount > 0


def get_filters(chat_id: str) -> List[dict]:
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT id, url, name, created_at FROM filter_urls WHERE chat_id = ? ORDER BY id DESC",
            (chat_id,)
        )
        return [dict(row) for row in cursor.fetchall()]


def get_all_filters() -> List[dict]:
    with get_db() as conn:
        cursor = conn.execute("SELECT chat_id, url FROM filter_urls")
        return [dict(row) for row in cursor.fetchall()]


def is_seen(listing_id: str) -> bool:
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT 1 FROM seen_listings WHERE listing_id = ?",
            (listing_id,)
        )
        return cursor.fetchone() is not None


def mark_seen(listing_id: str, title: str, price: str, url: str):
    with get_db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO seen_listings (listing_id, title, price, url) VALUES (?, ?, ?, ?)",
            (listing_id, title, price, url)
        )
        conn.commit()


# ============== OLX Scraper ==============

class OLXScraper:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})

    def extract_listing_id(self, url: str) -> Optional[str]:
        match = re.search(r'-ID([a-zA-Z0-9]+)\.html', url)
        return match.group(1) if match else None

    def fetch_listings(self, filter_url: str) -> list:
        try:
            response = self.session.get(filter_url, timeout=30)
            response.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"OLX error: {e}")
            return []

        soup = BeautifulSoup(response.text, 'html.parser')
        listings = []

        # JSON-LD dan ma'lumotlarni olish
        json_ld_data = {}
        for script in soup.select('script[type="application/ld+json"]'):
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and data.get('@type') == 'ItemList':
                    for item in data.get('itemListElement', []):
                        offer = item.get('item', {})
                        if offer.get('@type') == 'Offer':
                            url = offer.get('url', '')
                            listing_id = self.extract_listing_id(url)
                            if listing_id:
                                json_ld_data[listing_id] = {
                                    'title': offer.get('name', ''),
                                    'price': offer.get('price', ''),
                                    'currency': offer.get('priceCurrency', 'UZS'),
                                    'location': offer.get('areaServed', {}).get('name', ''),
                                    'url': url
                                }
            except (json.JSONDecodeError, TypeError):
                continue

        # HTML kartalardan ma'lumot
        cards = soup.select('[data-cy="l-card"]')

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

                # JSON-LD dan ma'lumot
                ld_info = json_ld_data.get(listing_id, {})

                # Rasm tagidagi div (img dan keyingi konteyner)
                img_elem = card.select_one('img')
                content_div = None
                if img_elem:
                    # Rasmni o'z ichiga olgan div'ni topib, uning keyingi sibling'ini olamiz
                    parent = img_elem.parent
                    while parent and parent != card:
                        next_sib = parent.find_next_sibling()
                        if next_sib:
                            content_div = next_sib
                            break
                        parent = parent.parent

                # Agar content_div topilmasa, kartaning o'zidan olamiz
                if not content_div:
                    content_div = card

                # Barcha matnlarni yig'ish
                all_texts = []
                for elem in content_div.find_all(['p', 'span', 'h6', 'div']):
                    text = elem.get_text(strip=True)
                    # Bo'sh emas, takrorlanmagan, qisqa
                    if text and text not in all_texts and 2 < len(text) < 150:
                        all_texts.append(text)

                # Title - birinchi uzun matn yoki JSON-LD dan
                title = ld_info.get('title', '')
                if not title and all_texts:
                    for t in all_texts:
                        if len(t) > 10:
                            title = t
                            break

                # Price - narx formatidagi matn
                price = ""
                if ld_info.get('price'):
                    price = f"{int(float(ld_info['price'])):,} {ld_info.get('currency', 'UZS')}".replace(',', ' ')
                else:
                    for t in all_texts:
                        if any(c in t.lower() for c in ['сум', 'usd', 'y.e', '$', 'у.е']):
                            price = t
                            break

                # Location (JSON-LD dan)
                location = ld_info.get('location', '')

                # Qolgan ma'lumotlar (title va price dan tashqari)
                details = []
                for t in all_texts:
                    if t != title and t != price and t not in details:
                        details.append(t)

                listings.append({
                    "id": listing_id,
                    "title": title or "E'lon",
                    "price": price or "Kelishiladi",
                    "url": href,
                    "location": location,
                    "details": details[:6]
                })
            except Exception as e:
                logger.warning(f"Parse error: {e}")

        return listings


scraper = OLXScraper()


# ============== Telegram ==============

def send_telegram(chat_id: str, text: str) -> bool:
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": False
            },
            timeout=30
        )
        return response.ok
    except Exception as e:
        logger.error(f"Telegram error: {e}")
        return False


def handle_message(chat_id: str, text: str):
    """Handle incoming message."""
    text = text.strip()

    if text == '/start':
        send_telegram(
            chat_id,
            "🔍 <b>OLX Kuzatuvchi</b>\n\n"
            "Men OLX.uz'dagi e'lonlarni kuzataman va yangilari haqida xabar beraman.\n\n"
            "<b>Buyruqlar:</b>\n"
            "/add [url] - Filter qo'shish\n"
            "/list - Filterlar ro'yxati\n"
            "/remove [id] - Filter o'chirish\n\n"
            "💡 OLX.uz dan URL to'g'ridan-to'g'ri yuborsangiz ham bo'ladi!"
        )

    elif text == '/help':
        send_telegram(
            chat_id,
            "📖 <b>Yordam</b>\n\n"
            "<b>Filter qo'shish:</b>\n"
            "1. OLX.uz saytida filterlarni tanlang\n"
            "2. URL'ni nusxalang\n"
            "3. Menga yuboring\n\n"
            "<b>Misol:</b>\n"
            "<code>https://www.olx.uz/nedvizhimost/kvartiry/prodazha/tashkent/</code>\n\n"
            "<b>Buyruqlar:</b>\n"
            "/add [url] - Filter qo'shish\n"
            "/list - Filterlar ro'yxati\n"
            "/remove [id] - Filter o'chirish\n\n"
            "⏱ Har 1 daqiqada tekshiriladi."
        )

    elif text == '/list':
        filters = get_filters(chat_id)
        if filters:
            msg = "📋 <b>Sizning filterlaringiz:</b>\n\n"
            for f in filters:
                short_url = f['url'][:50] + "..." if len(f['url']) > 50 else f['url']
                name = f['name'] or f"Filter #{f['id']}"
                msg += f"<b>ID: {f['id']}</b> - {name}\n{short_url}\n\n"
            msg += "O'chirish: /remove [id]"
            send_telegram(chat_id, msg)
        else:
            send_telegram(chat_id, "📭 Hozircha filter yo'q.\n\nOLX.uz dan URL yuboring.")

    elif text.startswith('/add'):
        url = text[4:].strip()
        if url:
            add_filter_url(chat_id, url)
        else:
            send_telegram(chat_id, "❌ URL kiriting.\n\nMisol: /add https://www.olx.uz/...")

    elif text.startswith('/remove'):
        id_str = text[7:].strip()
        if not id_str:
            send_telegram(chat_id, "❌ ID kiriting.\n\nMisol: /remove 1")
        else:
            try:
                filter_id = int(id_str)
                if remove_filter(chat_id, filter_id):
                    send_telegram(chat_id, "✅ Filter o'chirildi.")
                else:
                    send_telegram(chat_id, "❌ Filter topilmadi.")
            except ValueError:
                send_telegram(chat_id, "❌ Noto'g'ri ID.\n\n/list bilan tekshiring.")

    elif text.startswith("https://www.olx.uz"):
        add_filter_url(chat_id, text)

    elif not text.startswith('/'):
        send_telegram(chat_id, "❓ Noma'lum buyruq.\n\n/help - yordam")


def add_filter_url(chat_id: str, url: str):
    """Add filter URL and mark existing listings as seen."""
    if not url.startswith("https://www.olx.uz"):
        send_telegram(chat_id, "❌ Faqat OLX.uz havolalari qabul qilinadi.")
        return

    result = add_filter(chat_id, url)
    if result["success"]:
        send_telegram(chat_id, "⏳ Filter qo'shilmoqda...")
        # Mark existing listings as seen
        listings = scraper.fetch_listings(url)
        for listing in listings:
            mark_seen(listing['id'], listing['title'], listing['price'], listing['url'])
        send_telegram(chat_id, f"✅ Filter qo'shildi!\n\n{len(listings)} ta mavjud e'lon o'tkazib yuborildi.\nYangi e'lonlar haqida xabar beraman.")
    else:
        send_telegram(chat_id, f"⚠️ {result.get('error', 'Xatolik')}")


# ============== Polling ==============

def polling_loop():
    """Get updates from Telegram using long polling."""
    logger.info("Polling started")
    last_update_id = 0

    while True:
        try:
            response = requests.get(
                f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates",
                params={"offset": last_update_id + 1, "timeout": 30},
                timeout=35
            )

            if response.ok:
                data = response.json()
                for update in data.get("result", []):
                    last_update_id = update["update_id"]

                    if "message" in update:
                        message = update["message"]
                        chat_id = str(message["chat"]["id"])
                        text = message.get("text", "")

                        if text:
                            logger.info(f"Message from {chat_id}: {text[:50]}")
                            handle_message(chat_id, text)

        except Exception as e:
            logger.error(f"Polling error: {e}")
            time.sleep(5)


# ============== Checker ==============

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
                        # Xabar tuzish
                        lines = [f"🆕 <b>Yangi e'lon!</b>\n"]
                        lines.append(f"<b>{listing['title']}</b>\n")
                        lines.append(f"💰 {listing['price']}")

                        if listing.get('location'):
                            lines.append(f"📍 {listing['location']}")

                        # Qo'shimcha ma'lumotlar alohida qatorlarda
                        if listing.get('details'):
                            for detail in listing['details']:
                                lines.append(f"• {detail}")

                        lines.append(f"\n🔗 <a href=\"{listing['url']}\">E'lonni ko'rish</a>")

                        message = "\n".join(lines)
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

def main():
    if not BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set!")
        return

    logger.info("Starting OLX Bot...")

    # Delete any existing webhook
    try:
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook")
        logger.info("Webhook deleted")
    except:
        pass

    init_db()

    # Start checker thread
    checker_thread = threading.Thread(target=checker_loop, daemon=True)
    checker_thread.start()

    # Run polling (main thread)
    polling_loop()


if __name__ == '__main__':
    main()
