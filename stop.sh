#!/bin/bash
set -e

# --- CONFIGURATION ---
SERVICE_NAME="ChannelSaveBot"

echo "🛑 $SERVICE_NAME to'xtatilmoqda..."

# Service mavjudligini tekshirish
if systemctl list-unit-files | grep -q "^${SERVICE_NAME}.service"; then

    # Agar ishlayotgan bo'lsa, to'xtatish
    if systemctl is-active --quiet "$SERVICE_NAME"; then
        sudo systemctl stop "$SERVICE_NAME"
        echo "✅ Service to'xtatildi."
    else
        echo "ℹ️ Service allaqachon to'xtagan."
    fi

    # Auto-startni o'chirish
    sudo systemctl disable "$SERVICE_NAME" >/dev/null 2>&1 || true
    echo "✅ Auto-start o'chirildi."

else
    echo "❌ $SERVICE_NAME.service topilmadi."
    exit 1
fi

echo "🏁 Yakunlandi."