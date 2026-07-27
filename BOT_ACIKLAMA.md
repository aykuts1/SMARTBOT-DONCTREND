# SMARTBOT-MULTICOLOUR — Bot Nasıl Çalışır?

Tek stratejili bir kripto vadeli işlem (futures) botu — Bybit üzerinde, Stokastik + MACD kesişimine dayalı bir sinyal sistemi kullanıyor. `main.py` (`BotManager`) her şeyi orkestre ediyor; diğer modüller onun altında görev bölüşümü yapıyor.

## Dosyalar ve Görevleri

- `bybit_client.py` — Bybit REST API ile konuşan katman (bakiye, mum verisi, emir açma/kapama, pozisyon SL'i)
- `data_pool.py` — Her coin için mum geçmişi ve anlık fiyat cache'i
- `price_poller.py` — Fiyat ve mum kapanışı takibi
- `indicators.py` — Stokastik, MACD, Bollinger, ATR hesaplamaları
- `flag_manager.py` — İki indikatörün onaylaşma (flag) mantığı
- `strategy.py` — Sinyalden işlem isteğine dönüştürme (giriş/çıkış fiyatları)
- `trade_manager.py` — Sanal işlem takibi, pozisyon açma/kapama, risk kontrolleri
- `telegram_bot.py` — Bildirimler ve `/durum`, `/flagler`, `/yardim` komutları
- `state_store.py` — `bot_state.json` ile restart sonrası kalıcılık

## Veri Akışı (Zamanlama)

1. **Her 5 saniyede** (`price_poller.py`): Tüm coinlerin anlık fiyatı (`get_tickers`) çekilir, `data_pool`'a yazılır. Bu fiyatlar sadece **çıkış (exit) kontrolü** için kullanılır.
2. **Her 15 dakikalık mum kapanışında**: Poller mum sınırını (boundary) algılar, 5 saniye bekler (Bybit'in mumu kesinleştirmesi için), sonra kapanan mumu çeker ve `on_candle_close` callback'ini tetikler. Bu, **yeni sinyal üretimi**nin tek tetikleyicisidir.

Ayrıca ayrı bir arka plan döngüsü (`_scan_loop`, main.py) her 5 saniyede tüm açık sanal işlemler için exit fiyatını kontrol eder; 60 döngüde bir (~5 dk) borsa pozisyonlarıyla bot'un iç kaydı karşılaştırılır (reconcile).

## Sinyal Mantığı (indicators.py + flag_manager.py + strategy.py)

Her mum kapanışında `compute_signals`:
- **Stokastik** (K uzunluk 50, K smooth 21, D smooth 8) — %K/%D kesişimi
- **MACD** (hızlı 21, yavaş 50, sinyal 9) — MACD/sinyal çizgisi kesişimi
- **Bollinger Bantları** (20, 2 std) ve **ATR** (14) — çıkış seviyeleri için

### Flag sistemi (bağımsız long/short slotlar, her coin için ayrı)

- Bir indikatör (stokastik veya MACD) bir yönde kesişim verirse, o yönde bir "flag" açılır (kaynağı hangi indikatör olduğu kaydedilir).
- Flag açıkken diğer indikatör aynı yönde kesişim verirse → **işlem onaylanır**.
- 5 mum içinde onaylanmazsa flag silinir (süre doldu).
- Flag'i açan indikatör *aynı yönde* tekrar kesişim verirse, sayaç sıfırlanır (bekleme uzar) — bu, spesifikasyonda tanımsız bir durum için kullanıcının onayladığı güvenli bir varsayım.
- İki indikatör aynı mumda birlikte kesişim verirse, direkt onaylanır (flag'e gerek kalmadan).

## Giriş/Çıkış Hesabı (strategy.py)

Onay gelince:
- **Giriş fiyatı** = kapanan mumun close değeri
- **Lose exit** (zarar kes) = Bollinger bandının karşı ucu (long için alt bant, short için üst bant), ama ATR × 2'den (max_atr_carpani) daha uzaksa, mesafe ATR×2 ile sınırlanır (çok geniş stop'u önlemek için)
- **Win exit** (kâr al) = giriş fiyatından lose-exit mesafesinin 2.5 katı (rr_orani) uzaklıkta — yani Risk:Ödül = 1:2.5

## İşlem Açma (trade_manager.py)

Kontroller sırasıyla:
1. Toplam açık işlem limiti (max 20) ve coin+yön başına limit (max 2 — yani coin başına en fazla 2 long + 2 short = 4) doldu mu? Limit dolarsa Telegram'a "sinyal atlandı" bildirimi gönderilir.
2. Bakiye çekilir, pozisyon büyüklüğü = bakiyenin %5'i (marjin_orani) × 20x kaldıraç
3. Min. işlem büyüklüğü / borsa adım (step) kurallarına göre yuvarlanır; altında kalırsa sinyal atlanır ve Telegram'a bildirilir
4. Yetersiz bakiye varsa atlanır
5. Market emri gönderilir (3 deneme, aralarda 2sn bekleme), hedge modda (long/short aynı anda tutulabilir), IOC
6. Başarılıysa: pozisyonun tamamını kapsayan **%5 emniyet SL'i** borsaya gönderilir (asıl çıkış mantığı bot içinde çalıştığı için bu sadece bot çökerse diye bir güvenlik ağı)
7. İşlem bot içinde "sanal işlem" olarak kaydedilir — **önemli**: aynı coin+yönde birden fazla sinyal gelirse, borsada tek pozisyonda birleşirler ama bot her birini kendi giriş/çıkış seviyeleriyle ayrı ayrı izler.

## İşlem Kapatma

Her 5 saniyede fiyat, her sanal işlemin lose/win exit seviyeleriyle karşılaştırılır. Tetiklenirse reduce-only market emriyle o kadarlık miktar kapatılır (3 deneme), PnL hesaplanır, komisyon düşülür, `trade_history.py`'a kaydedilir ve Telegram'a bildirilir.

## Reconciliation (Uyum Kontrolü)

Periyodik olarak bot'un iç kaydındaki toplam miktar ile borsadaki gerçek pozisyon karşılaştırılır; %1'den fazla sapma varsa sadece **uyarı** gönderilir (otomatik düzeltme yapılmaz).

## Telegram Raporlama

- **Anlık bildirimler**: bot başladı/durdu, işlem açıldı/kapandı, sinyal atlandı (slot dolu / bakiye yetersiz / min büyüklük / emir hatası), pozisyon uyuşmazlığı
- **Periyodik raporlar**: 1 saatlik (açılan/kapanan/atlanan + bakiye), 6 saatlik (win rate + coin bazlı dağılım), 24 saatlik (toplam PnL, win rate, en aktif coin)
- **Komutlar**: `/durum` (anlık pozisyonlar + PnL), `/flagler` (onay bekleyen açık flagler), `/yardim`

## Kalıcılık (state_store.py)

Bot her state değişikliğinde (`_persist_state`) `bot_state.json`'a şunları yazar: açık sanal işlemler, açık flagler, telegram istatistikleri. Restart sonrası bunlar geri yüklenir, böylece bot kaldığı yerden devam eder.

## Konfigürasyon (config.json)

20 coin izleniyor (BTC, ETH, XRP, TRX, ADA, AVAX, DOGE, SOL, ATOM, NEAR, HYPE, WLD, SUI, DOT, DEXE, AKE, BNB, LTC, LINK, APT), 15 dakikalık zaman dilimi, 20x kaldıraç, %5 marjin oranı, RR 2.5, max ATR çarpanı 2 (daha sıkı stop mesafesi için kademeli düşürüldü: 4 → 3 → 2), coin+yön başına max 2 işlem (max_coin_yon_basi_islem).
