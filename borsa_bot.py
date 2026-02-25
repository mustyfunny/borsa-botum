import telebot
import yfinance as yf
import pandas as pd
import time
import threading
import warnings
import os
from flask import Flask

warnings.filterwarnings("ignore")

from ta.trend import MACD, SMAIndicator
from ta.momentum import RSIIndicator, StochasticOscillator
from ta.volatility import BollingerBands, AverageTrueRange

# --- BURAYA KENDİ BİLGİLERİNİ GİR ---
TELEGRAM_TOKEN = "8752151248:AAHgKlGYhGReXPkut4zIYqimAtbaVTdiiG0"
CHAT_ID = "5224140684"

bot = telebot.TeleBot(TELEGRAM_TOKEN)

# --- KALICI HAFIZA YÖNETİMİ ---
DOSYA_ADI = "takip_listesi.txt"
VARSAYILAN_HISSELER = ["AAPL", "NVDA", "THYAO.IS", "EREGL.IS"]

def hisseleri_yukle():
    if os.path.exists(DOSYA_ADI):
        with open(DOSYA_ADI, "r") as dosya:
            veri = dosya.read().strip()
            if veri:
                return veri.split(",")
    hisseleri_kaydet(VARSAYILAN_HISSELER)
    return VARSAYILAN_HISSELER.copy()

def hisseleri_kaydet(liste):
    with open(DOSYA_ADI, "w") as dosya:
        dosya.write(",".join(liste))

HISSELER = hisseleri_yukle()

# --- YENİ (v2.0): ENDEKS KONTROL SİSTEMİ (Önbellekli) ---
ENDEKS_CACHE = {
    "SPY": {"boga_mi": True, "son_guncelleme": 0},
    "XU100.IS": {"boga_mi": True, "son_guncelleme": 0}
}

def endeks_durumu_getir(para_birimi):
    sembol = "XU100.IS" if para_birimi == "₺" else "SPY"
    su_an = time.time()
    
    # API'yi yormamak için endeks verisini 1 saat (3600 sn) önbellekte tutarız
    if su_an - ENDEKS_CACHE[sembol]["son_guncelleme"] > 3600:
        try:
            data = yf.download(sembol, period="3mo", interval="1d", progress=False)
            if not data.empty:
                kapanis = data['Close'].squeeze()
                ma50 = SMAIndicator(close=kapanis, window=50).sma_indicator()
                fiyat = float(kapanis.iloc[-1])
                son_ma50 = float(ma50.iloc[-1])
                # Fiyat 50 günlük ortalamanın üstündeyse Boğa (Güvenli), altındaysa Ayı (Riskli) piyasası
                ENDEKS_CACHE[sembol]["boga_mi"] = fiyat > son_ma50
                ENDEKS_CACHE[sembol]["son_guncelleme"] = su_an
        except Exception:
            pass # Hata olursa eski veriyi (veya varsayılanı) kullanmaya devam et
            
    return ENDEKS_CACHE[sembol]["boga_mi"]


def analiz_et(ticker, rapor_modu=False):
    try:
        data = yf.download(ticker, period="1y", interval="1d", progress=False)
        if data.empty:
            if rapor_modu: return {"hata": f"⚠️ {ticker}: Veri bulunamadı."}
            return None

        para_birimi = "₺" if ticker.endswith(".IS") else "$"
        
        # YENİ (v2.0): Hissenin bağlı olduğu endeksin sağlığını kontrol et
        endeks_guvenli_mi = endeks_durumu_getir(para_birimi)

        kapanis = data['Close'].squeeze()
        yuksek = data['High'].squeeze()
        dusuk = data['Low'].squeeze()
        hacim = data['Volume'].squeeze()

        rsi = RSIIndicator(close=kapanis).rsi()
        macd = MACD(close=kapanis)
        stoch = StochasticOscillator(high=yuksek, low=dusuk, close=kapanis)
        bb = BollingerBands(close=kapanis)
        atr = AverageTrueRange(high=yuksek, low=dusuk, close=kapanis)
        
        ma20 = SMAIndicator(close=kapanis, window=20).sma_indicator()
        ma50 = SMAIndicator(close=kapanis, window=50).sma_indicator()
        ma200 = SMAIndicator(close=kapanis, window=200).sma_indicator()
        hacim_ortalamasi = hacim.rolling(window=20).mean()

        if pd.isna(rsi.iloc[-1]): return None

        fiyat = round(float(kapanis.iloc[-1]), 3)
        son_rsi = round(float(rsi.iloc[-1]), 2)
        son_macd = float(macd.macd().iloc[-1])
        son_macd_sinyal = float(macd.macd_signal().iloc[-1])
        stoch_k = float(stoch.stoch().iloc[-1])
        stoch_d = float(stoch.stoch_signal().iloc[-1])
        bb_alt = round(float(bb.bollinger_lband().iloc[-1]), 3)
        son_atr = float(atr.average_true_range().iloc[-1])
        son_hacim = float(hacim.iloc[-1])
        ort_hacim = float(hacim_ortalamasi.iloc[-1])
        son_ma20 = round(float(ma20.iloc[-1]), 3) if not pd.isna(ma20.iloc[-1]) else 0
        son_ma50 = round(float(ma50.iloc[-1]), 3) if not pd.isna(ma50.iloc[-1]) else 0
        son_ma200 = round(float(ma200.iloc[-1]), 3) if not pd.isna(ma200.iloc[-1]) else 0

        # YENİ (v2.0): Hacim Patlaması Kontrolü (Ortalamanın 3 katı)
        hacim_anormal_mi = son_hacim > (ort_hacim * 3)

        skor = 0
        if son_rsi < 45: skor += 15
        elif son_rsi < 55: skor += 5
        if stoch_k < 30 and stoch_k > stoch_d: skor += 15
        if son_macd > son_macd_sinyal: skor += 15
        if son_hacim > ort_hacim: skor += 10
        if fiyat > son_ma20 and son_ma20 != 0: skor += 10
        if son_ma20 > son_ma50 and son_ma50 != 0: skor += 15
        if fiyat > son_ma200 and son_ma200 != 0: skor += 10
        if fiyat <= (bb_alt * 1.05): skor += 10

        # YENİ (v2.0): Endeks Ayı piyasasındaysa riski azaltmak için skoru cezalandır
        if not endeks_guvenli_mi:
            skor -= 10 

        zarar_kes = round(fiyat - (son_atr * 1.5), 3)
        kar_al = round(fiyat + (son_atr * 3.0), 3)

        durum_ikonu = "🔥 GÜÇLÜ FIRSAT" if skor >= 75 else ("🟡 İZLEMEDE" if skor >= 50 else "🛑 UZAK DUR")
        
        rapor = f"📊 **{ticker} DETAYLI ANALİZ (v2.0)** 📊\n"
        rapor += f"💲 **Anlık Fiyat:** {para_birimi}{fiyat}\n"
        rapor += f"🎯 **Sistem Skoru:** {skor}/100 ({durum_ikonu})\n\n"
        
        # v2.0 Raporlama Eklemeleri
        if not endeks_guvenli_mi:
            rapor += f"⚠️ **ENDEKS UYARISI:** Piyasa genel trendi şu an DÜŞÜŞTE (MA50 Altında). İşlem açmak ekstra risklidir!\n\n"
        else:
            rapor += f"✅ **ENDEKS DURUMU:** Piyasa trendi POZİTİF (Rüzgar arkamızda).\n\n"
            
        if hacim_anormal_mi:
            rapor += f"🚨 **ANORMAL HACİM TESPİTİ:** Bu hissede son 20 günün ortalamasının 3 KATINDAN FAZLA işlem hacmi var! Büyük bir hareket kapıda olabilir.\n\n"

        rapor += f"📈 **TREND & ORTALAMALAR**\n▫️ Kısa Vade: {'🟢 MA20 Üstü' if fiyat > son_ma20 else '🔴 MA20 Altı'}\n▫️ Ana Trend: {'🟢 MA200 Üstü' if fiyat > son_ma200 else '🔴 MA200 Altı'}\n\n"
        rapor += f"⚡ **MOMENTUM & HACİM**\n▫️ RSI (14): {son_rsi} {'(🟢 Ucuz)' if son_rsi < 45 else ('(🔴 Pahalı)' if son_rsi > 70 else '(⚪ Nötr)')}\n"
        rapor += f"▫️ Stokastik: {'🟢 Dipte Kesişim' if stoch_k < 30 and stoch_k > stoch_d else '⚪ Normal'}\n▫️ Hacim: {'🟢 Ortalamanın Üstünde' if son_hacim > ort_hacim else '🔴 Zayıf'}\n"
        rapor += f"▫️ Bollinger: {'🟢 Alt Banda Yakın' if fiyat <= (bb_alt * 1.05) else '⚪ Bant İçinde'}\n\n"
        rapor += f"🛡️ **AKSİYON PLANI (ATR)**\n🛑 Zarar Kes: {para_birimi}{zarar_kes}\n💰 Hedef Kar: {para_birimi}{kar_al}\n"

        # Arka planda tựomatik fırsat yakalarsa (Normal puanı yüksekse VEYA hacim patlaması varsa haber ver)
        if not rapor_modu and (skor >= 75 or hacim_anormal_mi):
            bot.send_message(CHAT_ID, f"🚨 **OTOMATİK SİNYAL YAKALANDI** 🚨\n\n{rapor}")

        if rapor_modu: 
            return {"skor": skor, "fiyat": fiyat, "rapor": rapor, "para_birimi": para_birimi, "endeks_durum": endeks_guvenli_mi, "hacim_alarm": hacim_anormal_mi}
            
    except Exception as e:
        if rapor_modu: return {"hata": f"❌ {ticker}: Analiz hatası. ({e})"}
        return None

# --- TELEGRAM KOMUTLARI ---
@bot.message_handler(commands=['start', 'yardim', 'liste', 'ekle', 'sil', 'analiz', 'tara'])
def komut_yoneticisi(message):
    komut = message.text.split()[0]
    try:
        if komut in ['/start', '/yardim']:
            bot.reply_to(message, "🤖 Borsa Asistanı v2.0 Aktif! Komutlar: /liste, /ekle HISSE, /sil HISSE, /tara, /analiz HISSE")
        elif komut == '/liste':
            bot.reply_to(message, f"📋 Güncel Liste:\n{', '.join(HISSELER)}")
        elif komut == '/ekle':
            hisse = message.text.split()[1].upper()
            if hisse not in HISSELER:
                HISSELER.append(hisse)
                hisseleri_kaydet(HISSELER)
                bot.reply_to(message, f"✅ {hisse} eklendi!")
        elif komut == '/sil':
            hisse = message.text.split()[1].upper()
            if hisse in HISSELER:
                HISSELER.remove(hisse)
                hisseleri_kaydet(HISSELER)
                bot.reply_to(message, f"🗑️ {hisse} silindi.")
        elif komut == '/analiz':
            hisse = message.text.split()[1].upper()
            sonuc = analiz_et(hisse, rapor_modu=True)
            bot.send_message(message.chat.id, sonuc['rapor'] if "hata" not in sonuc else sonuc['hata'])
        elif komut == '/tara':
            bot.reply_to(message, "🔍 v2.0 Tarama başlatıldı (Piyasa Endeksi ve Hacim analizleri yapılıyor)...")
            ozet = "📊 **HIZLI TARAMA ÖZETİ (v2.0)** 📊\n\n"
            firsatlar = []
            
            for h in HISSELER:
                s = analiz_et(h, rapor_modu=True)
                if s and "hata" not in s:
                    ikon = "🔥" if s['skor'] >= 75 else ("🟡" if s['skor'] >= 50 else "🛑")
                    
                    # Özet listeye akıllı v2.0 ikonları ekleyelim
                    ek_uyari = ""
                    if not s['endeks_durum']: ek_uyari += " ⚠️"
                    if s['hacim_alarm']: ek_uyari += " 🚨"
                    
                    ozet += f"{ikon} **{h}:** {s['para_birimi']}{s['fiyat']} (Skor: {s['skor']}){ek_uyari}\n"
                    
                    # Detayını atacağı hisseler: Skoru yüksek olanlar VEYA hacmi patlayanlar
                    if s['skor'] >= 75 or s['hacim_alarm']: 
                        firsatlar.append(s['rapor'])
                elif s and "hata" in s:
                    ozet += f"⚠️ **{h}:** Veri Hatası\n"
            
            bot.send_message(message.chat.id, ozet)
            
            if firsatlar:
                bot.send_message(message.chat.id, "🎯 DİKKAT ÇEKEN FIRSATLAR VE ALARMLAR:")
                for r in firsatlar:
                    bot.send_message(message.chat.id, r)
                    time.sleep(0.5)
    except IndexError:
        bot.reply_to(message, "❌ Eksik bilgi! Kullanım: /ekle THYAO.IS veya /analiz AAPL")
    except Exception as e:
        bot.reply_to(message, f"❌ Hata: {e}")

# --- ARKA PLAN VE RENDER WEB SUNUCUSU ---
app = Flask(__name__)
@app.route('/')
def ana_sayfa(): return "Bot Başarıyla Çalışıyor! (v2.0)"

def otomatik_tarama():
    while True:
        for hisse in HISSELER: 
            analiz_et(hisse, rapor_modu=False)
        time.sleep(3600)

def bot_dinle():
    bot.infinity_polling()

if __name__ == "__main__":
    threading.Thread(target=otomatik_tarama, daemon=True).start()
    threading.Thread(target=bot_dinle, daemon=True).start()
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
