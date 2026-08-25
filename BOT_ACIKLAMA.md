# SMARTBOT-MULTICOLOUR — Bot Nasıl Çalışır?

Tek stratejili bir kripto vadeli işlem (futures) botu — Bybit Futures MAINNET üzerinde, **Fisher Transform (1H) tetikleyici + EMA(21/50/100, 1H) trend onayı + MACD(9/21 EMA karşılaştırması, 4H) onayı** üçlü sinyal sistemi kullanıyor. `main.py` (`BotManager`) her şeyi orkestre ediyor; diğer modüller onun altında görev bölüşümü yapıyor.

## Dosyalar ve Görevleri

- `bybit_client.py` — Bybit REST API katmanı (bakiye, mum verisi, market emir açma/kapama, pozisyon SL'i, tek yönlü pozisyon modu)
- `data_pool.py` — 1H ve 4H için ayrı ayrı, coin başına mum geçmişi ve son hesaplanan gösterge cache'i
- `price_poller.py` — 1H ve 4H mum kapanışlarını algılar, kapanan mumu çeker, ilgili callback'i tetikler (canlı fiyat takibi yok — tüm kararlar kapanmış mum üzerinden)
- `indicators.py` — EMA, Fisher Transform, MACD (EMA9 vs EMA21) hesaplamaları
- `strategy.py` — Fisher tetikleyici + EMA/MACD onayı → işlem açma/kapama kararı
- `trade_manager.py` — İşlem açma/kapama, pozisyon boyutlandırma, stop-loss, slot limiti, borsa-taraflı SL tetiklenmesini algılama
- `telegram_bot.py` — Bildirimler (giriş/çıkış/atlanan sinyal/periyodik rapor) ve `/durum`, `/yardim` komutları
- `trade_history.py` — Kapanan işlemlerin `trade_history.json`'a kaydı (sadece kayıt amaçlı, karar mekanizmasını etkilemez)

## Veri Akışı ve Sinyal Mantığı

1. **Her 1 saatlik mum kapanışında** (`strategy.on_1h_candle_close`): Fisher Transform(9) kısa çizginin uzun çizgiyi kesmesi tetikleyicidir (yukarı kesim → LONG adayı, aşağı kesim → SHORT adayı).
2. Tetikleyici yön, aynı mumda **EMA(21/50/100, 1H) net sıralaması** ve cache'lenmiş **MACD(9/21, 4H)** yönüyle karşılaştırılır. Üçü de aynı yöndeyse işlem açılır; biri bile uyuşmazsa "sinyal atlandı" bildirimi gönderilir.
3. **Her 4 saatlik mum kapanışında** (`strategy.on_4h_candle_close`): sadece MACD(9/21) yönü hesaplanıp `pool_4h` üzerinde cache'lenir — işlem açma/kapama yapmaz.
4. **Çıkış SADECE Fisher ters kesimiyle** olur. Ters kesim varsa mevcut pozisyon kapatılır; aynı mumda yeni yön koşulları sağlanıyorsa hemen yeni yönde giriş yapılır (flip, iki ayrı adım).
5. Borsaya girilen sabit **%4 stop-loss** ise mumlar arası tek güvenlik ağıdır; `trade_manager.poll_exchange_closures` her 5 saniyede borsadaki pozisyonları kontrol ederek SL tetiklenmesini algılar.

## Pozisyon Boyutu ve Risk (config.json → `global`)

Bakiyenin %10'u marj olarak ayrılır, 25x kaldıraçla notional büyütülür (`marjin_orani` × `kaldirac`). Coin başına en fazla 1, toplamda en fazla `maks_toplam_islem` (5) işlem açık olabilir. Ekstra take-profit yoktur.

## Restart Davranışı

Bot her yeniden başlatıldığında **tamamen sıfırdan** başlar: açık işlemler, slot sayacı ve Telegram rapor istatistikleri kalıcı hale getirilmez (state persistence yok). Restart öncesi borsada açık kalmış pozisyonlar bot tarafından yönetilmez, sadece loglanır; kendi başlarına sabit %4 SL ile kalırlar.

## Telegram Raporlama

- **Anlık bildirimler**: bot başladı/durdu, işlem açıldı/kapandı, sinyal atlandı (filtre uyuşmazlığı / slot dolu / bakiye yetersiz / min büyüklük / emir hatası)
- **Periyodik raporlar**: 6 saatlik ve 24 saatlik — açık pozisyonlar (coin, yön, anlık kâr/zarar), bakiye, dönem içi açılan/kapanan/atlanan sayıları, doluluk oranı (kaç/5 slot)
- **Komutlar**: `/durum` (anlık pozisyonlar + PnL + bakiye), `/yardim`

## Konfigürasyon (config.json)

28 coin izleniyor, 1H ana zaman dilimi + 4H MACD onay dilimi, 25x kaldıraç, %10 marjin oranı, %4 stop-loss, Fisher(9) + EMA(21/50/100) + MACD(9/21).
