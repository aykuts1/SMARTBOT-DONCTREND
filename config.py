import os

# --- Bybit API bilgileri (Railway environment variables'dan okunur) ---
BYBIT_API_KEY = os.environ.get("BYBIT_API_KEY", "")
BYBIT_API_SECRET = os.environ.get("BYBIT_API_SECRET", "")

# --- Telegram bilgileri ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# --- Taranacak coin listesi (28 parite) ---
SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "ADAUSDT", "AVAXUSDT", "WLDUSDT", "ONDOUSDT",
    "SUIUSDT", "HYPEUSDT", "INJUSDT", "ATOMUSDT", "XRPUSDT", "AAVEUSDT", "BNBUSDT",
    "DOGEUSDT", "ENAUSDT", "TAOUSDT", "TRXUSDT", "NEARUSDT", "OPUSDT", "TIAUSDT",
    "LTCUSDT", "ARBUSDT", "APTUSDT", "UNIUSDT", "TRUMPUSDT", "SHIB1000USDT", "1000PEPEUSDT",
]

# --- Zaman dilimleri (Bybit interval kodları: dakika cinsinden) ---
ENTRY_TIMEFRAME = "60"     # 1 saatlik -> ana tarama zaman dilimi
CONFIRM_TIMEFRAME = "240"  # 4 saatlik -> MACD onay zaman dilimi
KLINE_LIMIT = 200          # her iki zaman diliminde de çekilecek mum sayısı

# --- İndikatör ayarları ---
FISHER_PERIOD = 9

EMA_FAST = 21
EMA_MID = 50
EMA_SLOW = 100

MACD_FAST = 9
MACD_SLOW = 21

# --- Risk yönetimi ---
BALANCE_USAGE_PCT = 0.10   # her işlemde toplam bakiyenin %10'u marj olarak kullanılır
LEVERAGE = 25              # kaldıraç
MAX_OPEN_POSITIONS = 6     # tüm coinlerde birlikte açılabilecek maksimum işlem sayısı
STOP_LOSS_PCT = 0.08       # %8 stop loss

# --- Bybit API çağrıları arası bekleme (rate limit için) ---
API_CALL_DELAY_SEC = 0.3

# --- Railway "uykuya alma" özelliğini engellemek için, beklerken kaç saniyede
#     bir dışarıya küçük bir istek (keepalive) atılacağı ---
KEEPALIVE_INTERVAL_SEC = 300  # 5 dakika
