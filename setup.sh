#!/bin/bash

# OLX Apartment Notifier - Avtomatik o'rnatish scripti
# Ubuntu/Debian serverlar uchun

set -e

# Ranglar
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# O'rnatish joyi
INSTALL_DIR="/opt/olx-apartment-notifier"
SERVICE_NAME="olx-notifier"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}OLX Apartment Notifier - O'rnatish${NC}"
echo -e "${GREEN}========================================${NC}"

# Root tekshiruvi
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Iltimos, root sifatida ishga tushiring: sudo ./setup.sh${NC}"
    exit 1
fi

# 1. Tizimni yangilash
echo -e "\n${YELLOW}[1/6] Tizim paketlarini yangilamoqda...${NC}"
apt update -qq

# 2. Python va pip o'rnatish
echo -e "\n${YELLOW}[2/6] Python va pip o'rnatmoqda...${NC}"
apt install -y python3 python3-pip python3-venv -qq

# 3. O'rnatish papkasini yaratish
echo -e "\n${YELLOW}[3/6] Fayllarni ko'chirmoqda...${NC}"
mkdir -p "$INSTALL_DIR"
cp "$SCRIPT_DIR/olx_scraper.py" "$INSTALL_DIR/"
cp "$SCRIPT_DIR/requirements.txt" "$INSTALL_DIR/"
cp "$SCRIPT_DIR/config.example.json" "$INSTALL_DIR/"

# config.json mavjud bo'lsa ko'chirish
if [ -f "$SCRIPT_DIR/config.json" ]; then
    cp "$SCRIPT_DIR/config.json" "$INSTALL_DIR/"
    echo -e "${GREEN}config.json topildi va ko'chirildi${NC}"
else
    echo -e "${YELLOW}config.json topilmadi. O'rnatishdan keyin yarating.${NC}"
fi

# 4. Python kutubxonalarini o'rnatish
echo -e "\n${YELLOW}[4/6] Python kutubxonalarini o'rnatmoqda...${NC}"
pip3 install -r "$INSTALL_DIR/requirements.txt" -q

# 5. Systemd service yaratish
echo -e "\n${YELLOW}[5/6] Systemd service yaratmoqda...${NC}"
cat > "/etc/systemd/system/${SERVICE_NAME}.service" << EOF
[Unit]
Description=OLX Apartment Notifier Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=${INSTALL_DIR}
ExecStart=/usr/bin/python3 ${INSTALL_DIR}/olx_scraper.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# 6. Serviceni yoqish
echo -e "\n${YELLOW}[6/6] Serviceni sozlamoqda...${NC}"
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"

echo -e "\n${GREEN}========================================${NC}"
echo -e "${GREEN}O'rnatish muvaffaqiyatli yakunlandi!${NC}"
echo -e "${GREEN}========================================${NC}"

echo -e "\n${YELLOW}Keyingi qadamlar:${NC}"
echo -e "1. Konfiguratsiyani sozlang:"
echo -e "   ${GREEN}nano ${INSTALL_DIR}/config.json${NC}"
echo -e ""
echo -e "2. Serviceni ishga tushiring:"
echo -e "   ${GREEN}sudo systemctl start ${SERVICE_NAME}${NC}"
echo -e ""
echo -e "3. Holatni tekshiring:"
echo -e "   ${GREEN}sudo systemctl status ${SERVICE_NAME}${NC}"
echo -e ""
echo -e "4. Loglarni ko'ring:"
echo -e "   ${GREEN}sudo journalctl -u ${SERVICE_NAME} -f${NC}"

# Agar config.json yo'q bo'lsa, yaratishga yordam
if [ ! -f "$INSTALL_DIR/config.json" ]; then
    echo -e "\n${RED}DIQQAT: config.json fayli yo'q!${NC}"
    echo -e "Namuna fayldan yarating:"
    echo -e "   ${GREEN}cp ${INSTALL_DIR}/config.example.json ${INSTALL_DIR}/config.json${NC}"
    echo -e "   ${GREEN}nano ${INSTALL_DIR}/config.json${NC}"
fi
