# ✈️ Uçuş Fiyat Takip Telegram Botu

Her saat başı Skyscanner üzerinden uçak bileti fiyatlarını kontrol eden ve Telegram'a bildiren bot.

---

## 📦 Dosya Yapısı

```
flight-bot/
├── bot.py              # Ana bot mantığı
├── flight_checker.py   # Skyscanner API entegrasyonu
├── requirements.txt    # Python bağımlılıkları
├── Procfile            # Railway için başlatma komutu
└── .env.example        # Ortam değişkenleri şablonu
```

---

## 🔑 Gerekli API Anahtarları

### 1. Telegram Bot Token
1. Telegram'da **@BotFather**'a gidin
2. `/newbot` yazın
3. Bot adı ve kullanıcı adı girin
4. Size verilen token'ı kopyalayın → `TELEGRAM_BOT_TOKEN`

### 2. Skyscanner RapidAPI Key
1. https://rapidapi.com/skyscanner/api/skyscanner50 adresine gidin
2. Ücretsiz hesap oluşturun (aylık 100 istek ücretsiz)
3. "Subscribe" → Free plan seçin
4. `X-RapidAPI-Key` değerini kopyalayın → `RAPIDAPI_KEY`

---

## 🚀 Railway'e Deploy

### Adım 1: GitHub Repo Oluşturun
```bash
git init
git add .
git commit -m "initial commit"
git branch -M main
git remote add origin https://github.com/KULLANICI_ADINIZ/flight-bot.git
git push -u origin main
```

### Adım 2: Railway Kurulumu
1. https://railway.app adresine gidin (GitHub ile giriş yapın)
2. **"New Project"** → **"Deploy from GitHub repo"** seçin
3. Oluşturduğunuz repo'yu seçin
4. **"Add Variables"** bölümüne gidin ve şunları ekleyin:

```
TELEGRAM_BOT_TOKEN = your_token_here
RAPIDAPI_KEY       = your_key_here
```

5. **"Deploy"** butonuna tıklayın

### Adım 3: Worker Servisi Ayarı
Railway'de proje açıldıktan sonra:
- **Settings** → **Start Command**: `python bot.py`
- Veya Procfile otomatik algılanır

---

## 💬 Bot Komutları

| Komut | Açıklama |
|-------|----------|
| `/start` | Botu başlat, yardım mesajı |
| `/watch` | Yeni rota takibi başlat |
| `/list` | Aktif takibini göster |
| `/check` | Şimdi fiyat kontrol et |
| `/stop` | Takibi durdur |
| `/cancel` | İşlemi iptal et |

---

## 📱 Kullanım Örneği

```
/watch
→ Kalkış: IST
→ Varış: LHR
→ Gidiş tarihi: 15.07.2025
→ Gidiş-dönüş: Evet
→ Dönüş tarihi: 22.07.2025
→ Yolcu sayısı: 2
→ Onayla ✅
```

Bot her saat başı (XX:00) otomatik fiyat kontrolü yapar ve şu formatta mesaj atar:

```
✈️ IST → LHR
🔄 Gidiş-Dönüş | 📅 15.07.2025 / 22.07.2025 | 👥 2 yolcu
🕐 Kontrol: 22.04.2025 14:00
──────────────────────────────
🥇 12,450 ₺  (kişi başı ~6,225 ₺)
   🛫 Gidiş: Turkish Airlines
   15.07 06:30 → 15.07 09:45 (3s 15dk, Aktarmasız)
   🛬 Dönüş: Turkish Airlines
   22.07 11:00 → 22.07 16:20 (3s 20dk, Aktarmasız)
...
```

---

## ⚙️ Teknik Notlar

- **APScheduler** ile her saat başı `cron(minute=0)` tetiklenir
- **aiohttp** ile async API çağrısı yapılır
- **python-telegram-bot v20** ConversationHandler kullanır
- Birden fazla kullanıcı aynı anda farklı rotaları takip edebilir
- `active_watches` sözlüğü bot çalıştığı sürece bellekte tutulur (Railway restart olursa sıfırlanır)

---

## 🔧 Lokal Test

```bash
pip install -r requirements.txt
cp .env.example .env
# .env dosyasını düzenleyin
export $(cat .env | xargs)
python bot.py
```

---

## 📈 Geliştirme Fikirleri

- [ ] SQLite ile takipleri kalıcı hale getir
- [ ] Fiyat eşiği: "X TL altına düşünce bildir"
- [ ] Birden fazla rota takibi
- [ ] Grafik: son 24 saatin fiyat değişimi
- [ ] Inline klavye ile sık kullanılan rotalar
