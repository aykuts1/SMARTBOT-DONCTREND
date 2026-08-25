# Bybit Futures Trading Bot

Bu bot, Bybit Futures'ta (USDT Perpetual, gerçek hesap — testnet DEĞİL) 28 coin üzerinde
Fisher Transform, EMA (21/50/100) ve MACD (9/21) indikatörlerini kullanarak otomatik
long/short işlem açan ve Telegram üzerinden bildirim gönderen bir sistemdir.

## Nasıl çalışır (özet)

- Bot 1 saatlik mum kapanışlarında tarama yapar.
- **Fisher (1H)** tetiği verir, **EMA (1H)** ve **MACD (4H)** onaylarsa işlem açılır.
- Onaylardan biri eksikse sinyal atlanır, Telegram'a sebebiyle bildirim gider.
- Çıkış **sadece** Fisher sinyaline bağlıdır. Ayrıca her pozisyona **%8 Stop Loss** konur.
- Bir coinde en fazla 1, toplamda en fazla 6 işlem aynı anda açık olabilir.
- Her işlemde bakiyenin %10'u marj olarak kullanılır, 25x kaldıraç ve Cross Margin ile.
- Bot her tur sonunda (giriş/çıkış işlemleri bitince) o turda taranan, işlem açılan ve
  sinyal gelmeyen coinlerin özetini Telegram'a "Tur Özeti" olarak gönderir.
- Bot beklerken (bir sonraki mum kapanışını beklerken) her 5 dakikada bir Bybit'e küçük
  bir istek atar (keepalive). Bu, Railway'in "Serverless / App Sleeping" özelliğinin
  botu uykuya almasını engellemek içindir.

## Dosya yapısı

| Dosya | Görevi |
|---|---|
| `main.py` | Zamanlayıcı — her şeyi sırayla tetikleyen ana döngü |
| `config.py` | Tüm ayarlar (coin listesi, indikatör periyotları, risk oranları) |
| `bybit_client.py` | Bybit API ile veri çekme ve emir gönderme |
| `indicators.py` | Fisher, EMA, MACD hesaplamaları |
| `strategy.py` | Giriş/çıkış/atlama kararını üreten mantık |
| `risk_manager.py` | Slot kontrolü ve pozisyon büyüklüğü hesabı |
| `notifier.py` | Telegram bildirimleri |
| `state.py` | Açık pozisyonların bellekte tutulması |
| `utils.py` | Sayı yuvarlama/formatlama yardımcıları |

## Railway'e deploy etme

1. Bu klasördeki tüm dosyaları GitHub'da yeni bir repo'ya yükle.
2. Railway'de **New Project → Deploy from GitHub repo** ile bu repo'yu seç.
3. Railway otomatik olarak `Procfile`'ı görüp `python main.py` komutunu bir **worker**
   olarak çalıştıracaktır. Eğer çalıştırmazsa, Railway proje ayarlarından
   **Settings → Deploy → Start Command** kısmına elle `python main.py` yaz.
4. **Variables** sekmesine gidip şu 4 değişkeni ekle (`.env.example` dosyasına bak):
   - `BYBIT_API_KEY`
   - `BYBIT_API_SECRET`
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
5. Deploy tamamlanınca Railway loglarında ve Telegram'da "Bot başlatıldı" mesajını göreceksin.

### Bybit API key nasıl alınır (özet)
Bybit hesabında **API** bölümünden yeni key oluştur, **Contract Trading (Futures)**
için okuma+yazma (read-write) izni ver. Para çekme (withdraw) iznini KAPALI bırak —
bot'un buna ihtiyacı yok, güvenlik için gereksiz risk almamak adına kapalı kalması iyi olur.

### Telegram bot token / chat id nasıl alınır (özet)
Telegram'da **@BotFather**'a `/newbot` yazarak bir bot oluştur, sana vereceği token'ı
`TELEGRAM_BOT_TOKEN` olarak kullan. Kendi chat id'ni öğrenmek için oluşturduğun bota
bir mesaj at, sonra `https://api.telegram.org/bot<TOKEN>/getUpdates` adresini tarayıcıda
aç; dönen JSON içindeki `"chat":{"id": ...}` değeri senin `TELEGRAM_CHAT_ID`'n.

## Railway "Serverless" ayarını da kontrol et

Bot beklerken her 5 dakikada bir keepalive isteği atsa da, ekstra güvence için Railway
proje ayarlarında **Settings → Deploy → Serverless** kısmına gidip bu özelliğin
**kapalı** olduğundan emin ol. Normalde varsayılan olarak kapalıdır ama proje ayarlarına
göre açık gelebiliyor; açık kalırsa bot yine de uykuya dalabilir.

## Bybit hesap ayarı — ÖNEMLİ

Bot **One-Way (Tek Yönlü) pozisyon modu** varsayımıyla yazıldı (bir coinde aynı anda
sadece long YA DA short olabileceği için buna ihtiyaç var, Hedge Mode gerekmiyor).
Bybit hesabında Futures bölümünde pozisyon modunun **One-Way** olduğundan emin ol,
aksi halde emir gönderiminde hata alınabilir.

## Kodu yazarken yaptığım birkaç yorum/varsayım

Bunları protokolde net konuşmadığımız için burada belirtiyorum, yanlışsa söyle, değiştiririm:

- **"Toplam bakiye"** olarak Bybit UNIFIED hesabın `totalAvailableBalance` (yeni işlem
  açmak için kullanılabilir toplam bakiye) değerini kullandım.
- **Durum raporları**: Saat 6 ve 24'e denk geldiğinde 3 ayrı mesaj yerine, o saate ait
  en üst seviye rapor (örneğin 24. saatte "24 Saatlik Rapor") tek mesaj olarak gönderiliyor.
  İstersen bunu 3 ayrı mesaj gönderecek şekilde değiştirebilirim.
- **SL borsa tarafında tetiklenirse** (yani Fisher sinyali gelmeden önce %8'e ulaşılırsa),
  bot bunu bir sonraki taramada fark edip pozisyonu hafızasından siliyor ve Telegram'a
  bildirim gönderiyor. Bu olmadan slot sayısı yanlış kalırdı.
- Bot restart olursa **hiçbir state dosyasına yazmıyor** — konuştuğumuz gibi, açık
  pozisyonları borsadan da geri okumuyor, sıfırdan başlıyor. Eğer restart anında gerçekte
  açık bir pozisyon varsa, bot onu bilmeyecek ve o coin için tekrar sinyal ararken slot
  sayımı gerçek durumla bir tur boyunca uyuşmayabilir.

## Kısa bir risk notu

25x kaldıraç ile Cross Margin kullanıldığında, likidasyon mesafesi sadece o pozisyona
ayrılan marja değil, hesaptaki **kullanılmayan toplam bakiyeye** de bağlıdır (Cross Margin
tüm bakiyeyi ortak teminat olarak kullanır). Bu yüzden %8 SL'nin gerçekte tetiklenip
tetiklenmeyeceği, o an kaç slotun dolu olduğuna ve hesabın toplam durumuna göre değişebilir.
Bu bir hata değil, kaldıraç + cross margin mekaniğinin doğal sonucu — bilgin olsun istedim.
