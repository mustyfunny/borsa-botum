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


def analiz_et(ticker, rapor_modu=False):
    try:
        data = yf.download(ticker, period="1y", interval="1d", progress=False)
        if data.empty:
            if rapor_modu: return {"hata": f"⚠️ {ticker}: Veri bulunamadı."}
            return None

        para_birimi = "₺" if ticker.endswith(".IS") else "$"
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

        zarar_kes = round(fiyat - (son_atr * 1.5), 3)
        kar_al = round(fiyat + (son_atr * 3.0), 3)

        durum_ikonu = "🔥 GÜÇLÜ FIRSAT" if skor >= 75 else ("🟡 İZLEMEDE" if skor >= 50 else "🛑 UZAK DUR")
        
        rapor = f"📊 **{ticker} DETAYLI ANALİZ** 📊\n💲 **Anlık Fiyat:** {para_birimi}{fiyat}\n🎯 **Sistem Skoru:** {skor}/100 ({durum_ikonu})\n\n"
        rapor += f"📈 **TREND & ORTALAMALAR**\n▫️ Kısa Vade: {'🟢 MA20 Üstü' if fiyat > son_ma20 else '🔴 MA20 Altı'}\n▫️ Ana Trend: {'🟢 MA200 Üstü' if fiyat > son_ma200 else '🔴 MA200 Altı'}\n\n"
        rapor += f"⚡ **MOMENTUM & HACİM**\n▫️ RSI (14): {son_rsi} {'(🟢 Ucuz)' if son_rsi < 45 else ('(🔴 Pahalı)' if son_rsi > 70 else '(⚪ Nötr)')}\n"
        rapor += f"▫️ Stokastik: {'🟢 Dipte Kesişim' if stoch_k < 30 and stoch_k > stoch_d else '⚪ Normal'}\n▫️ Hacim: {'🟢 Ortalamanın Üstünde' if son_hacim > ort_hacim else '🔴 Zayıf'}\n"
        rapor += f"▫️ Bollinger: {'🟢 Alt Banda Yakın' if fiyat <= (bb_alt * 1.05) else '⚪ Bant İçinde'}\n\n"
        rapor += f"🛡️ **AKSİYON PLANI (ATR)**\n🛑 Zarar Kes: {para_birimi}{zarar_kes}\n💰 Hedef Kar: {para_birimi}{kar_al}\n"

        if not rapor_modu and skor >= 75: bot.send_message(CHAT_ID, f"🚨 **OTOMATİK SİNYAL YAKALANDI** 🚨\n\n{rapor}")
        if rapor_modu: return {"skor": skor, "fiyat": fiyat, "rapor": rapor, "para_birimi": para_birimi}
            
    except Exception as e:
        if rapor_modu: return {"hata": f"❌ {ticker}: Analiz hatası. ({e})"}
        return None

# --- TELEGRAM KOMUTLARI ---
@bot.message_handler(commands=['start', 'yardim', 'liste', 'ekle', 'sil', 'analiz', 'tara'])
def komut_yoneticisi(message):
    komut = message.text.split()[0]
    try:
        if komut in ['/start', '/yardim']:
            bot.reply_to(message, "🤖 Borsa Asistanı Aktif! Komutlar: /liste, /ekle HISSE, /sil HISSE, /tara, /analiz HISSE")
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
            bot.send_message(CHAT_ID, sonuc['rapor'] if "hata" not in sonuc else sonuc['hata'])
        elif komut == '/tara':
            bot.reply_to(message, "🔍 Özet rapor hazırlanıyor...")
            ozet = "📊 **HIZLI TARAMA ÖZETİ** 📊\n\n"
            firsatlar = []
            for h in HISSELER:
                s = analiz_et(h, rapor_modu=True)
                if s and "hata" not in s:
                    ikon = "🔥" if s['skor'] >= 75 else ("🟡" if s['skor'] >= 50 else "🛑")
                    ozet += f"{ikon} **{h}:** {s['para_birimi']}{s['fiyat']} (Skor: {s['skor']}/100)\n"
                    if s['skor'] >= 75: firsatlar.append(s['rapor'])
                elif s and "hata" in s:
                    ozet += f"⚠️ **{h}:** Veri Hatası\n"
            bot.send_message(CHAT_ID, ozet)
            if firsatlar:
                bot.send_message(CHAT_ID, "🎯 GÜÇLÜ FIRSATLAR:")
                for r in firsatlar:
                    bot.send_message(CHAT_ID, r)
                    time.sleep(0.5)
    except:
        bot.reply_to(message, "❌ Hatalı kullanım!")

# --- ARKA PLAN VE RENDER WEB SUNUCUSU ---
app = Flask(__name__)
@app.route('/')
def ana_sayfa(): return "Bot Başarıyla Çalışıyor!"

def otomatik_tarama():
    while True:
        for hisse in HISSELER: analiz_et(hisse)
        time.sleep(3600)

def bot_dinle():
    bot.infinity_polling()

if __name__ == "__main__":
    threading.Thread(target=otomatik_tarama, daemon=True).start()
    threading.Thread(target=bot_dinle, daemon=True).start()
    # Render'ın botu kapatmaması için sahte web sunucusunu başlatıyoruz
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)