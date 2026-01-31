#!/usr/bin/env python3
"""
OLX.uz kvartira e'lonlarini kuzatuvchi va Telegram orqali xabar yuboruvchi bot.
"""

import json
import re
import sqlite3
import time
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup

# Logging sozlamalari
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('olx_scraper.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Konstantalar
BASE_URL = "https://www.olx.uz"
LISTINGS_URL = f"{BASE_URL}/nedvizhimost/kvartiry/prodazha/"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


class Database:
    """SQLite ma'lumotlar bazasi bilan ishlash."""

    def __init__(self, db_path: str = "seen_listings.db"):
        self.db_path = db_path
        self.init_db()

    def init_db(self):
        """Ma'lumotlar bazasini yaratish."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS seen_listings (
                    listing_id TEXT PRIMARY KEY,
                    title TEXT,
                    price TEXT,
                    url TEXT,
                    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()

    def is_seen(self, listing_id: str) -> bool:
        """E'lon avval ko'rilganmi tekshirish."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT 1 FROM seen_listings WHERE listing_id = ?",
                (listing_id,)
            )
            return cursor.fetchone() is not None

    def mark_seen(self, listing_id: str, title: str, price: str, url: str):
        """E'lonni ko'rilgan deb belgilash."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO seen_listings (listing_id, title, price, url) VALUES (?, ?, ?, ?)",
                (listing_id, title, price, url)
            )
            conn.commit()


class TelegramNotifier:
    """Telegram orqali xabar yuborish."""

    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.api_url = f"https://api.telegram.org/bot{bot_token}"

    def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        """Telegram'ga xabar yuborish."""
        try:
            response = requests.post(
                f"{self.api_url}/sendMessage",
                json={
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": parse_mode,
                    "disable_web_page_preview": False
                },
                timeout=30
            )
            response.raise_for_status()
            return True
        except requests.RequestException as e:
            logger.error(f"Telegram xabar yuborishda xato: {e}")
            return False


class OLXScraper:
    """OLX.uz saytidan e'lonlarni parse qilish."""

    def __init__(self, config: dict):
        self.config = config
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self.db = Database()
        self.notifier = TelegramNotifier(
            config["telegram"]["bot_token"],
            config["telegram"]["chat_id"]
        )

    def build_url(self) -> str:
        """Filter parametrlari bilan URL yaratish."""
        filters = self.config.get("filters", {})
        url = LISTINGS_URL

        # Shahar filtri
        city = filters.get("city")
        if city:
            url = f"{BASE_URL}/nedvizhimost/kvartiry/prodazha/{city}/"

        params = []

        # Narx filtri
        min_price = filters.get("min_price")
        max_price = filters.get("max_price")
        if min_price:
            params.append(f"search[filter_float_price:from]={min_price}")
        if max_price:
            params.append(f"search[filter_float_price:to]={max_price}")

        # Xonalar soni
        min_rooms = filters.get("min_rooms")
        max_rooms = filters.get("max_rooms")
        if min_rooms:
            params.append(f"search[filter_enum_rooms][0]={min_rooms}")
        if max_rooms and max_rooms != min_rooms:
            for i, rooms in enumerate(range(min_rooms or 1, max_rooms + 1)):
                params.append(f"search[filter_enum_rooms][{i}]={rooms}")

        if params:
            url += "?" + "&".join(params)

        return url

    def extract_listing_id(self, url: str) -> Optional[str]:
        """E'lon URL'dan ID ajratib olish."""
        match = re.search(r'-ID([a-zA-Z0-9]+)\.html', url)
        if match:
            return match.group(1)
        return None

    def parse_price(self, price_text: str) -> Optional[int]:
        """Narx matnidan raqamni ajratib olish."""
        if not price_text:
            return None
        numbers = re.findall(r'\d+', price_text.replace(" ", ""))
        if numbers:
            return int("".join(numbers))
        return None

    def fetch_listings(self) -> list:
        """OLX'dan e'lonlar ro'yxatini olish."""
        url = self.build_url()
        logger.info(f"E'lonlarni yuklamoqda: {url}")

        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"OLX'ga ulanishda xato: {e}")
            return []

        soup = BeautifulSoup(response.text, 'html.parser')
        listings = []

        # E'lonlarni topish (OLX'ning yangi dizayni)
        cards = soup.select('[data-cy="l-card"]')

        if not cards:
            # Eski dizayn uchun
            cards = soup.select('.offer-wrapper')

        for card in cards:
            try:
                # Havola va sarlavha
                link_elem = card.select_one('a[href*="/d/"]') or card.select_one('a.marginright5')
                if not link_elem:
                    continue

                href = link_elem.get('href', '')
                if not href.startswith('http'):
                    href = BASE_URL + href

                listing_id = self.extract_listing_id(href)
                if not listing_id:
                    continue

                # Sarlavha
                title_elem = card.select_one('h6') or card.select_one('.title-cell strong')
                title = title_elem.get_text(strip=True) if title_elem else "Sarlavhasiz"

                # Narx
                price_elem = card.select_one('[data-testid="ad-price"]') or card.select_one('.price strong')
                price_text = price_elem.get_text(strip=True) if price_elem else "Narx ko'rsatilmagan"

                # Manzil
                location_elem = card.select_one('[data-testid="location-date"]') or card.select_one('.breadcrumb')
                location = location_elem.get_text(strip=True) if location_elem else ""

                listings.append({
                    "id": listing_id,
                    "title": title,
                    "price": price_text,
                    "url": href,
                    "location": location
                })

            except Exception as e:
                logger.warning(f"E'lonni parse qilishda xato: {e}")
                continue

        logger.info(f"{len(listings)} ta e'lon topildi")
        return listings

    def format_message(self, listing: dict) -> str:
        """Telegram xabari uchun formatlash."""
        return f"""🏠 <b>Yangi e'lon!</b>

<b>{listing['title']}</b>

💰 Narxi: {listing['price']}
📍 {listing['location']}

🔗 <a href="{listing['url']}">E'lonni ko'rish</a>"""

    def process_listings(self):
        """Yangi e'lonlarni qayta ishlash va xabar yuborish."""
        listings = self.fetch_listings()
        new_count = 0

        for listing in listings:
            if not self.db.is_seen(listing['id']):
                logger.info(f"Yangi e'lon: {listing['title']}")

                # Telegram'ga yuborish
                message = self.format_message(listing)
                if self.notifier.send_message(message):
                    self.db.mark_seen(
                        listing['id'],
                        listing['title'],
                        listing['price'],
                        listing['url']
                    )
                    new_count += 1
                    time.sleep(1)  # Rate limiting

        if new_count > 0:
            logger.info(f"{new_count} ta yangi e'lon yuborildi")
        else:
            logger.info("Yangi e'lon topilmadi")

    def run(self):
        """Asosiy loop - doimiy kuzatish."""
        interval = self.config.get("check_interval", 300)
        logger.info(f"Bot ishga tushdi. Tekshirish oralig'i: {interval} soniya")

        while True:
            try:
                self.process_listings()
            except Exception as e:
                logger.error(f"Xato yuz berdi: {e}")

            logger.info(f"Keyingi tekshirishgacha {interval} soniya kutilmoqda...")
            time.sleep(interval)


def load_config(config_path: str = "config.json") -> dict:
    """Konfiguratsiya faylini o'qish."""
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(
            f"Konfiguratsiya fayli topilmadi: {config_path}\n"
            "config.example.json dan config.json yarating."
        )

    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def main():
    """Asosiy funksiya."""
    try:
        config = load_config()
        scraper = OLXScraper(config)
        scraper.run()
    except FileNotFoundError as e:
        logger.error(e)
    except KeyboardInterrupt:
        logger.info("Bot to'xtatildi")
    except Exception as e:
        logger.error(f"Kutilmagan xato: {e}")
        raise


if __name__ == "__main__":
    main()
