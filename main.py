import logging 
import os
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
BOT_TOKEN = os.environ.get("BOT_TOKEN")
SHEET_NAME = "Penjualan"

# ==================== MENU & HARGA ====================
MENU = {
    "paket_teman_dekat": {"nama": "Paket Teman Dekat 🍩❤️", "harga": 40000},
    "paket_teman_manis": {"nama": "Paket Teman Manis 🍩🌸", "harga": 20000},
    "donat_pcs":         {"nama": "Donat PCS 🍩", "harga": 7000},
}

PEMBAYARAN = {
    "qris": "QRIS 📱",
    "cash": "Cash 💵",
}

# ==================== STATE ====================
PILIH_MENU, PILIH_JUMLAH, PILIH_BAYAR, KONFIRMASI = range(4)

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ==================== GOOGLE SHEETS ====================
def get_sheet():
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]
    creds_json = json.loads(os.environ.get("GOOGLE_CREDENTIALS"))
    spreadsheet_id = os.environ.get("SPREADSHEET_ID")
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_json, scope)
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(spreadsheet_id)
    try:
        sheet = spreadsheet.worksheet(SHEET_NAME)
    except gspread.WorksheetNotFound:
        sheet = spreadsheet.add_worksheet(title=SHEET_NAME, rows=1000, cols=10)
        sheet.append_row(["No", "Tanggal", "Waktu", "Produk", "Jumlah", "Harga Satuan", "Total", "Metode Bayar", "User Telegram"])
    return sheet

def simpan_ke_sheet(data: dict):
    sheet = get_sheet()
    no = sheet.get_all_values().__len__()
    now = datetime.now()
    sheet.append_row([
        no,
        now.strftime("%d/%m/%Y"),
        now.strftime("%H:%M:%S"),
        data["produk"],
        data["jumlah"],
        data["harga_satuan"],
        data["total"],
        data["pembayaran"],
        data["username"],
    ])

def get_rekap_hari_ini():
    sheet = get_sheet()
    rows = sheet.get_all_values()
    if len(rows) <= 1:
        return None
    today = datetime.now().strftime("%d/%m/%Y")
    rekap = {}
    total_omzet = 0
    for row in rows[1:]:
        if len(row) >= 8 and row[1] == today:
            produk = row[3]
            jumlah = int(row[4]) if row[4] else 0
            total = int(row[6]) if row[6] else 0
            if produk not in rekap:
                rekap[produk] = {"jumlah": 0, "total": 0}
            rekap[produk]["jumlah"] += jumlah
            rekap[produk]["total"] += total
            total_omzet += total
    return rekap, total_omzet

# ==================== HELPER ====================
def fmt(angka):
    return f"{angka:,}".replace(",", ".")

# ==================== HANDLERS ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🛒 Catat Penjualan", callback_data="catat")],
        [InlineKeyboardButton("📊 Rekap Hari Ini", callback_data="rekap")],
    ]
    await update.message.reply_text(
        "🍩 *Bot Penjualan Donat*\n\nHalo! Mau ngapain?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def menu_utama_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("🛒 Catat Penjualan", callback_data="catat")],
        [InlineKeyboardButton("📊 Rekap Hari Ini", callback_data="rekap")],
    ]
    await query.edit_message_text(
        "🍩 *Bot Penjualan Donat*\n\nMau ngapain?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def catat_penjualan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("Paket Teman Dekat 🍩❤️\nRp 40.000", callback_data="paket_teman_dekat")],
        [InlineKeyboardButton("Paket Teman Manis 🍩🌸\nRp 20.000", callback_data="paket_teman_manis")],
        [InlineKeyboardButton("Donat PCS 🍩\nRp 7.000", callback_data="donat_pcs")],
        [InlineKeyboardButton("❌ Batal", callback_data="batal")],
    ]
    await query.edit_message_text(
        "🍩 *Pilih Produk:*",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return PILIH_MENU

async def pilih_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    key = query.data
    produk = MENU[key]
    context.user_data["produk"] = produk["nama"]
    context.user_data["harga_satuan"] = produk["harga"]
    await query.edit_message_text(
        f"✅ Produk: *{produk['nama']}*\n💰 Harga: Rp {fmt(produk['harga'])}\n\nMasukkan *jumlah* yang terjual (ketik angka):",
        parse_mode="Markdown"
    )
    return PILIH_JUMLAH

async def pilih_jumlah(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        jumlah = int(update.message.text.strip())
        if jumlah <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Masukkan angka yang benar:")
        return PILIH_JUMLAH

    context.user_data["jumlah"] = jumlah
    context.user_data["total"] = jumlah * context.user_data["harga_satuan"]
    keyboard = [
        [
            InlineKeyboardButton("QRIS 📱", callback_data="qris"),
            InlineKeyboardButton("Cash 💵", callback_data="cash"),
        ],
        [InlineKeyboardButton("❌ Batal", callback_data="batal")],
    ]
    await update.message.reply_text(
        f"✅ Jumlah: *{jumlah} pcs*\n💰 Total: *Rp {fmt(context.user_data['total'])}*\n\nPilih *metode pembayaran:*",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return PILIH_BAYAR

async def pilih_bayar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["pembayaran"] = PEMBAYARAN[query.data]
    d = context.user_data
    keyboard = [
        [InlineKeyboardButton("✅ Simpan", callback_data="simpan")],
        [InlineKeyboardButton("❌ Batal", callback_data="batal")],
    ]
    await query.edit_message_text(
        f"📋 *Ringkasan Penjualan:*\n\n"
        f"🍩 Produk: {d['produk']}\n"
        f"🔢 Jumlah: {d['jumlah']} pcs\n"
        f"💰 Harga Satuan: Rp {fmt(d['harga_satuan'])}\n"
        f"💵 Total: Rp {fmt(d['total'])}\n"
        f"💳 Pembayaran: {d['pembayaran']}\n\n"
        f"Konfirmasi data di atas?",
        reply_markup=InlineKeyboardMarkup(keyboard),
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
        keyboard = [
            [InlineKeyboardButton("🛒 Catat Lagi", callback_data="catat")],
            [InlineKeyboardButton("📊 Rekap Hari Ini", callback_data="rekap")],
        ]
        await query.edit_message_text(
            "✅ *Penjualan berhasil dicatat!*\n\nData sudah masuk ke Google Sheets 📊",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error simpan: {e}")
        await query.edit_message_text(f"❌ Gagal menyimpan: {str(e)}")
    context.user_data.clear()
    return ConversationHandler.END

async def rekap_hari_ini(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        result = get_rekap_hari_ini()
        today = datetime.now().strftime("%d/%m/%Y")
        keyboard = [
            [InlineKeyboardButton("🛒 Catat Penjualan", callback_data="catat")],
            [InlineKeyboardButton("🔄 Refresh", callback_data="rekap")],
        ]
        if not result or not result[0]:
            await query.edit_message_text(
                f"📊 Belum ada penjualan hari ini ({today}).\n\nYuk catat penjualan! 🍩",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            rekap, total_omzet = result
            teks = f"📊 *Rekap Penjualan {today}*\n\n"
            for produk, info in rekap.items():
                teks += f"🍩 *{produk}*\n"
                teks += f"   Terjual: {info['jumlah']} pcs\n"
                teks += f"   Total: Rp {fmt(info['total'])}\n\n"
            teks += f"💰 *Total Omzet: Rp {fmt(total_omzet)}*"
            await query.edit_message_text(teks, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error rekap: {e}")
        await query.edit_message_text(f"❌ Gagal mengambil rekap: {str(e)}")
    return ConversationHandler.END

async def batal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    keyboard = [[InlineKeyboardButton("🏠 Menu Utama", callback_data="menu_utama")]]
    await query.edit_message_text("❌ Dibatalkan.", reply_markup=InlineKeyboardMarkup(keyboard))
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
        per_message=False,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(menu_utama_cb, pattern="^menu_utama$"))
    app.add_handler(CallbackQueryHandler(rekap_hari_ini, pattern="^rekap$"))

    logger.info("🍩 Bot Donat berjalan...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
