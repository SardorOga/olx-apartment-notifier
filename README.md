# OLX.uz Kvartira E'lonlari Kuzatuvchi Bot

OLX.uz saytidagi kvartira sotish e'lonlarini avtomatik kuzatib, yangi e'lonlar haqida Telegram orqali xabar beruvchi bot.

## Xususiyatlar

- 🏠 OLX.uz'dan kvartira sotish e'lonlarini avtomatik kuzatish
- 📱 Yangi e'lonlar haqida Telegram orqali real-time xabar olish
- 🔍 Shahar, narx va xonalar soni bo'yicha filtrlash
- 🗄️ SQLite orqali dublikat e'lonlarni oldini olish
- ⚙️ Sozlanishi oson konfiguratsiya fayli
- 🖥️ Systemd service sifatida serverda ishga tushirish

## O'rnatish

### 1. Telegram Bot yaratish

1. Telegram'da [@BotFather](https://t.me/BotFather) ga yozing
2. `/newbot` buyrug'ini yuboring
3. Bot uchun nom va username kiriting
4. BotFather sizga `bot_token` beradi - uni saqlang

### 2. Chat ID olish

1. Yaratilgan botingizga biror xabar yuboring
2. Brauzerda quyidagi URL'ni oching (TOKEN o'rniga o'z tokeningizni qo'ying):
   ```
   https://api.telegram.org/botTOKEN/getUpdates
   ```
3. Javobda `"chat":{"id":123456789}` ko'rinishida chat_id ni toping

### 3. Kodni yuklab olish

```bash
git clone https://github.com/SardorOga/olx-apartment-notifier.git
cd olx-apartment-notifier
```

### 4. Kutubxonalarni o'rnatish

```bash
pip3 install -r requirements.txt
```

### 5. Konfiguratsiya

```bash
cp config.example.json config.json
nano config.json
```

`config.json` faylini tahrirlang:

```json
{
    "telegram": {
        "bot_token": "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz",
        "chat_id": "123456789"
    },
    "filters": {
        "city": "tashkent",
        "min_price": 50000,
        "max_price": 150000,
        "min_rooms": 2,
        "max_rooms": 4
    },
    "check_interval": 300
}
```

### Konfiguratsiya parametrlari

| Parametr | Tavsif | Misol |
|----------|--------|-------|
| `bot_token` | Telegram bot tokeni | `1234567890:ABC...` |
| `chat_id` | Telegram chat ID | `123456789` |
| `city` | Shahar (URL'dagi nom) | `tashkent`, `samarkand` |
| `min_price` | Minimal narx (USD) | `50000` |
| `max_price` | Maksimal narx (USD) | `150000` |
| `min_rooms` | Minimal xonalar soni | `2` |
| `max_rooms` | Maksimal xonalar soni | `4` |
| `check_interval` | Tekshirish oralig'i (soniya) | `300` (5 daqiqa) |

## Ishga tushirish

### Lokal ishga tushirish

```bash
python3 olx_scraper.py
```

### Serverda doimiy ishga tushirish

#### Avtomatik o'rnatish (tavsiya etiladi)

```bash
chmod +x setup.sh
sudo ./setup.sh
```

#### Qo'lda o'rnatish

1. Systemd service faylini yarating:

```bash
sudo nano /etc/systemd/system/olx-notifier.service
```

2. Quyidagi kontentni qo'shing:

```ini
[Unit]
Description=OLX Apartment Notifier Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/olx-apartment-notifier
ExecStart=/usr/bin/python3 /opt/olx-apartment-notifier/olx_scraper.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

3. Serviceni yoqing:

```bash
sudo systemctl daemon-reload
sudo systemctl enable olx-notifier
sudo systemctl start olx-notifier
```

### Service boshqarish buyruqlari

```bash
# Holatni ko'rish
sudo systemctl status olx-notifier

# To'xtatish
sudo systemctl stop olx-notifier

# Qayta ishga tushirish
sudo systemctl restart olx-notifier

# Loglarni ko'rish
sudo journalctl -u olx-notifier -f
```

## Fayl tuzilmasi

```
olx-apartment-notifier/
├── olx_scraper.py      # Asosiy bot kodi
├── config.json         # Konfiguratsiya (yaratilishi kerak)
├── config.example.json # Namuna konfiguratsiya
├── requirements.txt    # Python kutubxonalari
├── setup.sh           # Avtomatik o'rnatish scripti
├── seen_listings.db   # Ko'rilgan e'lonlar bazasi (avtomatik yaratiladi)
├── olx_scraper.log    # Log fayli (avtomatik yaratiladi)
└── README.md          # Ushbu hujjat
```

## Xatoliklarni tuzatish

### "Konfiguratsiya fayli topilmadi"
`config.example.json` dan `config.json` yarating va sozlang.

### Telegram xabarlari kelmayapti
1. Bot tokenini tekshiring
2. Chat ID to'g'riligini tekshiring
3. Botga avval biror xabar yuborganingizga ishonch hosil qiling

### E'lonlar topilmayapti
1. OLX.uz saytida qo'lda tekshiring - filterlar to'g'ri sozlanganmi
2. `olx_scraper.log` faylini tekshiring

## Litsenziya

MIT License

## Muallif

[@SardorOga](https://github.com/SardorOga)
