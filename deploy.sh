#!/bin/bash
set -e  # Xato bo‘lsa darhol to‘xtaydi

# --- CONFIGURATION ---
# Bot nomi (repo nomi bilan bir xil bo‘lsa yaxshi)
SERVICE_NAME="ChannelSaveBot"  # Bu botning systemd service nomi
APP_DIR="$(pwd)"  # Script ishlayotgan papka = repo root
BRANCH="main"  # Git branch
PYTHON="$APP_DIR/venv/bin/python"  # Virtualenv python

# --- Virtualenv yaratish (agar mavjud bo'lmasa) ---
if [ ! -d "$APP_DIR/venv" ]; then
    echo "🌿 Virtualenv topilmadi, yaratilmoqda..."
    python3 -m venv "$APP_DIR/venv"
fi

# --- DEPLOY START ---
echo "🚀 Deploy boshlanmoqda: $SERVICE_NAME"
echo "📁 Papka: $APP_DIR"
echo "🌿 Branch: $BRANCH"

# 1️⃣ Git pull
echo "📥 Git pull..."
git fetch origin "$BRANCH"
git reset --hard "origin/$BRANCH"

# 2️⃣ Dependency tekshirish
echo "📦 Dependency tekshirilmoqda..."
if [ -f "$APP_DIR/requirements.txt" ]; then
    "$PYTHON" -m pip install -r "$APP_DIR/requirements.txt"
fi

# 3️⃣ systemd service yangilash
echo "⚙️ systemd service yangilanmoqda..."
if [ -f "$APP_DIR/systemd/$SERVICE_NAME.service" ]; then
    sudo cp "$APP_DIR/systemd/$SERVICE_NAME.service" /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable "$SERVICE_NAME"
    sudo systemctl restart "$SERVICE_NAME"
else
    echo "❌ $SERVICE_NAME.service topilmadi systemd papkada!"
    exit 1
fi

echo "✅ Deploy tugadi: $SERVICE_NAME"
