import requests

import config


def send_message(text: str):
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        print(f"[UYARI] Telegram ayarları eksik, mesaj gönderilemedi:\n{text}")
        return

    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        resp = requests.post(
            url,
            data={
                "chat_id": config.TELEGRAM_CHAT_ID,
                "text": text,
                "parse_mode": "HTML",
            },
            timeout=10,
        )
        if resp.status_code != 200:
            print(f"[HATA] Telegram mesajı gönderilemedi ({resp.status_code}): {resp.text}")
    except Exception as e:
        print(f"[HATA] Telegram mesajı gönderilemedi: {e}")
