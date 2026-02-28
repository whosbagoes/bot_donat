"""
Bot Telegram - Tracker Penjualan Donat 🍩
==========================================
Cara setup:
1. pip install python-telegram-bot gspread oauth2client
2. Isi BOT_TOKEN dan SPREADSHEET_ID di bawah
3. Siapkan Google Service Account (lihat README)
4. Jalankan: python bot_donat.py
"""

import logging
import json
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, ConversationHandler, MessageHandler, filters
)
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# ==================== KONFIGURASI ====================
BOT_TOKEN = "8696717037:AAEr5wrj0VGCUbEJ8RwHJ89E53t8LpZacy0"
SPREADSHEET_ID = "1OKqxHaP5-3_aTGzOMRlPwMiaRqmdffdT1HvHSMzjugk"
CREDENTIALS_FILE = "credentials.json"  # File service account Google
SHEET_NAME = "Penjualan"               # Nama sheet di Google Sheets

# ==================== MENU & HARGA ====================
MENU = {
    "paket_teman_dekat": {"nama": "Paket Teman Dekat 🍩❤️", "harga": 40000},
    "paket_teman_manis": {"nama": "Paket Teman Manis 🍩🌸", "harga": 20000},
    "donat_pcs": {"nama": "Donat PCS 🍩", "harga": 7000},
}

PEMBAYARAN = {
    "qris": "QRIS 📱",
    "cash": "Cash 💵",
}

# ==================== STATE CONVERSATION ====================
PILIH_MENU, PILIH_JUMLAH, PILIH_BAYAR, KONFIRMASI = range(4)

# ==================== LOGGING ====================
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ==================== GOOGLE SHEETS ====================
def get_sheet():
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(SPREADSHEET_ID)
    
    # Cek apakah sheet sudah ada, kalau belum buat baru
    try:
        sheet = spreadsheet.worksheet(SHEET_NAME)
    except gspread.WorksheetNotFound:
        sheet = spreadsheet.add_worksheet(title=SHEET_NAME, rows=1000, cols=10)
        # Tambahkan header
        sheet.append_row([
            "No", "Tanggal", "Waktu", "Produk", "Jumlah",
            "Harga Satuan", "Total", "Metode Bayar", "User Telegram"
        ])
    return sheet

def simpan_ke_sheet(data: dict):
    sheet = get_sheet()
    semua_data = sheet.get_all_values()
    no = len(semua_data)  # Nomor urut otomatis (baris pertama = header)
    
    now = datetime.now()
    row = [
        no,
        now.strftime("%d/%m/%Y"),
        now.strftime("%H:%M:%S"),
        data["produk"],
        data["jumlah"],
        data["harga_satuan"],
        data["total"],
        data["pembayaran"],
        data["username"],
    ]
    sheet.append_row(row)

def get_rekap_hari_ini():
    sheet = get_sheet()
    semua_data = sheet.get_all_values()
    if len(semua_data) <= 1:
        return None
    
    today = datetime.now().strftime("%d/%m/%Y")
    rekap = {}
    total_omzet = 0
    
    for row in semua_data[1:]:  # Skip header
        if len(row) >= 8 and row[1] == today:
            produk = row[3]
            jumlah = int(row[4]) if row[4] else 0
            total = int(row[6]) if row[6] else 0
            metode = row[7]
            
            if produk not in rekap:
                rekap[produk] = {"jumlah": 0, "total": 0}
            rekap[produk]["jumlah"] += jumlah
            rekap[produk]["total"] += total
            total_omzet += total
    
    return rekap, total_omzet

# ==================== HANDLER BOT ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🛒 Catat Penjualan", callback_data="catat")],
        [InlineKeyboardButton("📊 Rekap Hari Ini", callback_data="rekap")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "🍩 *Bot Penjualan Donat*\n\nHalo! Selamat datang. Mau ngapain nih?",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def menu_utama(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("🛒 Catat Penjualan", callback_data="catat")],
        [InlineKeyboardButton("📊 Rekap Hari Ini", callback_data="rekap")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        "🍩 *Bot Penjualan Donat*\n\nMau ngapain?",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def catat_penjualan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton(v["nama"] + f"\nRp {v['harga']:,}", callback_data=k)]
        for k, v in MENU.items()
    ]
    keyboard.append([InlineKeyboardButton("❌ Batal", callback_data="batal")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "🍩 *Pilih Produk:*",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )
    return PILIH_MENU

async def pilih_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    produk_key = query.data
    context.user_data["produk_key"] = produk_key
    context.user_data["produk"] = MENU[produk_key]["nama"]
    context.user_data["harga_satuan"] = MENU[produk_key]["harga"]
    
    await query.edit_message_text(
        f"✅ Produk: *{MENU[produk_key]['nama']}*\n"
        f"💰 Harga: Rp {MENU[produk_key]['harga']:,}\n\n"
        f"Masukkan *jumlah* yang terjual (ketik angka):",
        parse_mode="Markdown"
    )
    return PILIH_JUMLAH

async def pilih_jumlah(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        jumlah = int(update.message.text.strip())
        if jumlah <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Jumlah tidak valid. Masukkan angka yang benar:")
        return PILIH_JUMLAH
    
    context.user_data["jumlah"] = jumlah
    context.user_data["total"] = jumlah * context.user_data["harga_satuan"]
    
    keyboard = [
        [InlineKeyboardButton(v, callback_data=k) for k, v in PEMBAYARAN.items()],
        [InlineKeyboardButton("❌ Batal", callback_data="batal")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"✅ Jumlah: *{jumlah} pcs*\n"
        f"💰 Total: *Rp {context.user_data['total']:,}*\n\n"
        f"Pilih *metode pembayaran:*",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )
    return PILIH_BAYAR

async def pilih_bayar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    context.user_data["pembayaran"] = PEMBAYARAN[query.data]
    
    data = context.user_data
    keyboard = [
        [InlineKeyboardButton("✅ Konfirmasi & Simpan", callback_data="simpan")],
        [InlineKeyboardButton("❌ Batal", callback_data="batal")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f"📋 *Ringkasan Penjualan:*\n\n"
        f"🍩 Produk: {data['produk']}\n"
        f"🔢 Jumlah: {data['jumlah']} pcs\n"
        f"💰 Harga Satuan: Rp {data['harga_satuan']:,}\n"
        f"💵 Total: Rp {data['total']:,}\n"
        f"💳 Pembayaran: {data['pembayaran']}\n\n"
        f"Konfirmasi data di atas?",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )
    return KONFIRMASI

async def simpan_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    context.user_data["username"] = f"@{user.username}" if user.username else user.first_name
    
    try:
        simpan_ke_sheet(context.user_data)
        await query.edit_message_text(
            f"✅ *Penjualan berhasil dicatat!*\n\n"
            f"Data sudah tersimpan ke Google Sheets 📊",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error simpan sheet: {e}")
        await query.edit_message_text(
            f"❌ Gagal menyimpan data: {str(e)}\n\nCek koneksi & konfigurasi Google Sheets.",
        )
    
    # Balik ke menu utama
    keyboard = [[InlineKeyboardButton("🏠 Menu Utama", callback_data="menu_utama")]]
    await query.message.reply_text(
        "Mau catat lagi?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    context.user_data.clear()
    return ConversationHandler.END

async def rekap_hari_ini(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    try:
        result = get_rekap_hari_ini()
        if result is None or not result[0]:
            await query.edit_message_text(
                "📊 Belum ada penjualan hari ini.\n\n"
                "Yuk catat penjualan pertamamu! 🍩"
            )
        else:
            rekap, total_omzet = result
            today = datetime.now().strftime("%d/%m/%Y")
            teks = f"📊 *Rekap Penjualan {today}*\n\n"
            for produk, info in rekap.items():
                teks += f"🍩 *{produk}*\n"
                teks += f"   Terjual: {info['jumlah']} pcs\n"
                teks += f"   Total: Rp {info['total']:,}\n\n"
            teks += f"💰 *Total Omzet: Rp {total_omzet:,}*"
            
            keyboard = [[InlineKeyboardButton("🏠 Menu Utama", callback_data="menu_utama")]]
            await query.edit_message_text(
                teks,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
    except Exception as e:
        logger.error(f"Error rekap: {e}")
        await query.edit_message_text(f"❌ Gagal mengambil rekap: {str(e)}")
    
    return ConversationHandler.END

async def batal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    keyboard = [[InlineKeyboardButton("🏠 Menu Utama", callback_data="menu_utama")]]
    await query.edit_message_text(
        "❌ Dibatalkan.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ConversationHandler.END

# ==================== MAIN ====================
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(catat_penjualan, pattern="^catat$")],
        states={
            PILIH_MENU: [CallbackQueryHandler(pilih_menu, pattern="^(paket_teman_dekat|paket_teman_manis|donat_pcs)$")],
            PILIH_JUMLAH: [MessageHandler(filters.TEXT & ~filters.COMMAND, pilih_jumlah)],
            PILIH_BAYAR: [CallbackQueryHandler(pilih_bayar, pattern="^(qris|cash)$")],
            KONFIRMASI: [CallbackQueryHandler(simpan_data, pattern="^simpan$")],
        },
        fallbacks=[CallbackQueryHandler(batal, pattern="^batal$")],
    )
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(menu_utama, pattern="^menu_utama$"))
    app.add_handler(CallbackQueryHandler(rekap_hari_ini, pattern="^rekap$"))
    
    print("🍩 Bot Donat berjalan...")
    app.run_polling()

if __name__ == "__main__":
    main()
