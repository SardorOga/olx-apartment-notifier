# OLX.uz Kvartira Kuzatuvchi - Telegram Mini App

Telegram Mini App orqali OLX.uz'dagi kvartira e'lonlarini kuzating va yangi e'lonlar haqida avtomatik xabar oling.

## Xususiyatlar

- 🏠 OLX.uz'dagi kvartira e'lonlarini kuzatish
- 📱 Telegram Mini App - chiroyli va qulay interfeys
- 🔗 Istalgancha filter URL qo'shish
- ⚡ Har 1 daqiqada avtomatik tekshirish
- 🔔 Yangi e'lonlar haqida darhol xabar

## Qanday ishlaydi

1. Telegram botga `/start` yuboring
2. "Filterlarni boshqarish" tugmasini bosing
3. OLX.uz dan filter URL'ini qo'shing
4. Yangi e'lonlar haqida avtomatik xabar olasiz!

## O'rnatish (GitHub Actions bilan)

### 1. Telegram Bot yaratish

1. [@BotFather](https://t.me/BotFather) ga `/newbot` yuboring
2. Bot nomini kiriting
3. Bot token'ni oling

### 2. GitHub Secrets sozlash

Repository → Settings → Secrets and variables → Actions → New repository secret:

| Secret | Qiymat |
|--------|--------|
| `SSH_HOST` | Server IP (masalan: `161.97.146.226`) |
| `SSH_USER` | `root` |
| `SSH_PASSWORD` | Server paroli |
| `TELEGRAM_BOT_TOKEN` | Bot token |
| `WEBAPP_URL` | `http://[SERVER_IP]` |

### 3. Deploy

Push qiling yoki Actions → Run workflow

### 4. Bot Menu sozlash (ixtiyoriy)

BotFather'da:
1. `/mybots` → botingizni tanlang
2. Bot Settings → Menu Button
3. URL: `http://[SERVER_IP]`
4. Title: "🏠 Filterlar"

## Texnologiyalar

- **Backend**: Python, Flask, Gunicorn
- **Frontend**: Telegram Web App SDK
- **Database**: SQLite
- **Server**: Nginx reverse proxy
- **CI/CD**: GitHub Actions

## Fayl tuzilmasi

```
olx-apartment-notifier/
├── bot.py              # Backend (Flask + Bot)
├── webapp/
│   └── index.html      # Mini App frontend
├── requirements.txt
├── .github/
│   └── workflows/
│       └── deploy.yml  # Auto deploy
└── README.md
```

## Serverda boshqarish

```bash
# Status
sudo systemctl status olx-bot

# Restart
sudo systemctl restart olx-bot

# Logs
sudo journalctl -u olx-bot -f
```

## Litsenziya

MIT License
