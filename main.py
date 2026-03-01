import logging 
import os
import json
import pytz
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
WIB = pytz.timezone("Asia/Jakarta")

# ==================== MENU & HARGA ====================
MENU = {
    "paket_teman_dekat": {"nama": "Paket Teman Dekat", "harga": 40000, "emoji": "🍩❤️"},
    "paket_teman_manis": {"nama": "Paket Teman Manis", "harga": 20000, "emoji": "🍩🌸"},
    "donat_pcs":         {"nama": "Donat PCS", "harga": 7000,  "emoji": "🍩"},
}

PEMBAYARAN = {
    "qris": "QRIS 📱",
    "cash": "Cash 💵",
}

# ==================== STATE ====================
PILIH_PRODUK, PILIH_BAYAR, KONFIRMASI = range(3)

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
        sheet = spreadsheet.add_worksheet(title=SHEET_NAME, rows=1000, cols=9)
        sheet.append_row(["No", "Tanggal", "Waktu", "Produk", "Jumlah", "Harga Satuan", "Total", "Metode Bayar", "User Telegram"])
    return sheet

def parse_angka(nilai):
    if not nilai:
        return 0
    nilai = str(nilai).replace("Rp", "").replace(",", "").replace(".", "").strip()
    try:
        return int(float(nilai))
    except:
        return 0

def simpan_ke_sheet(items: list, pembayaran: str, username: str):
    sheet = get_sheet()
    no = len(sheet.get_all_values())
    now = datetime.now(WIB)
    for item in items:
        sheet.append_row([
            no,
            now.strftime("%d/%m/%Y"),
            now.strftime("%H:%M:%S"),
            item["nama"],
            item["jumlah"],
            item["harga_satuan"],
            item["total"],
            pembayaran,
            username,
        ])
        no += 1

def get_rekap_hari_ini():
    sheet = get_sheet()
    rows = sheet.get_all_values()
    if len(rows) <= 1:
        return None
    today = datetime.now(WIB).strftime("%d/%m/%Y")
    rekap = {}
    total_omzet = 0
    for row in rows[1:]:
        if len(row) >= 8 and row[1] == today:
            produk = row[3]
            jumlah = parse_angka(row[4])
            total = parse_angka(row[6])
            if produk not in rekap:
                rekap[produk] = {"jumlah": 0, "total": 0}
            rekap[produk]["jumlah"] += jumlah
            rekap[produk]["total"] += total
            total_omzet += total
    return rekap, total_omzet

def fmt(angka):
    return f"{int(angka):,}".replace(",", ".")

# ==================== KEYBOARD HELPER ====================
def build_menu_keyboard(selected: dict):
    """Buat keyboard produk dengan tanda ✅ jika sudah dipilih dan ada jumlahnya"""
    keyboard = []
    for key, produk in MENU.items():
        jumlah = selected.get(key, 0)
        if jumlah > 0:
            label = f"✅ {produk['emoji']} {produk['nama']} x{jumlah} — Rp {fmt(produk['harga'] * jumlah)}"
        else:
            label = f"{produk['emoji']} {produk['nama']} — Rp {fmt(produk['harga'])}"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"pilih_{key}")])

    # Tombol bawah
    bawah = []
    if selected:
        bawah.append(InlineKeyboardButton("🗑 Reset", callback_data="reset_pilihan"))
    if any(v > 0 for v in selected.values()):
        bawah.append(InlineKeyboardButton("➡️ Lanjut", callback_data="lanjut_bayar"))
    if bawah:
        keyboard.append(bawah)
    keyboard.append([InlineKeyboardButton("❌ Batal", callback_data="batal")])
    return InlineKeyboardMarkup(keyboard)

def build_jumlah_keyboard(key: str):
    """Keyboard pilih jumlah 1-10"""
    produk = MENU[key]
    keyboard = []
    row = []
    for i in range(1, 11):
        row.append(InlineKeyboardButton(str(i), callback_data=f"jumlah_{key}_{i}"))
        if len(row) == 5:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("❌ Batal", callback_data="batal")])
    return InlineKeyboardMarkup(keyboard), produk

def ringkasan_items(selected: dict) -> str:
    teks = ""
    total_semua = 0
    for key, jumlah in selected.items():
        if jumlah > 0:
            produk = MENU[key]
            subtotal = produk["harga"] * jumlah
            total_semua += subtotal
            teks += f"  {produk['emoji']} {produk['nama']} x{jumlah} = Rp {fmt(subtotal)}\n"
    teks += f"\n💰 *Total: Rp {fmt(total_semua)}*"
    return teks, total_semua

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
    context.user_data.clear()
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
    context.user_data.clear()
    context.user_data["selected"] = {}
    await query.edit_message_text(
        "🍩 *Pilih Produk:*\n\nTap produk untuk memilih, tap lagi untuk ubah jumlah.",
        reply_markup=build_menu_keyboard({}),
        parse_mode="Markdown"
    )
    return PILIH_PRODUK

async def pilih_produk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    key = query.data.replace("pilih_", "")
    context.user_data["pilih_key"] = key
    produk = MENU[key]
    keyboard, _ = build_jumlah_keyboard(key)
    await query.edit_message_text(
        f"🍩 *{produk['nama']}*\nRp {fmt(produk['harga'])} / pcs\n\nPilih jumlah:",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    return PILIH_PRODUK

async def pilih_jumlah_produk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, key, jumlah_str = query.data.split("_", 2)
    # handle key yang mengandung underscore (paket_teman_dekat dll)
    parts = query.data.split("_")
    jumlah = int(parts[-1])
    key = "_".join(parts[1:-1])

    selected = context.user_data.get("selected", {})
    selected[key] = jumlah
    context.user_data["selected"] = selected

    await query.edit_message_text(
        "🍩 *Pilih Produk:*\n\nTap produk untuk memilih, tap lagi untuk ubah jumlah.",
        reply_markup=build_menu_keyboard(selected),
        parse_mode="Markdown"
    )
    return PILIH_PRODUK

async def reset_pilihan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["selected"] = {}
    await query.edit_message_text(
        "🍩 *Pilih Produk:*\n\nTap produk untuk memilih, tap lagi untuk ubah jumlah.",
        reply_markup=build_menu_keyboard({}),
        parse_mode="Markdown"
    )
    return PILIH_PRODUK

async def lanjut_bayar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    selected = context.user_data.get("selected", {})
    teks_ring, _ = ringkasan_items(selected)
    keyboard = [
        [
            InlineKeyboardButton("QRIS 📱", callback_data="qris"),
            InlineKeyboardButton("Cash 💵", callback_data="cash"),
        ],
        [InlineKeyboardButton("❌ Batal", callback_data="batal")],
    ]
    await query.edit_message_text(
        f"🛒 *Pesanan:*\n{teks_ring}\n\nPilih *metode pembayaran:*",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return PILIH_BAYAR

async def pilih_bayar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pembayaran = PEMBAYARAN[query.data]
    context.user_data["pembayaran"] = pembayaran
    selected = context.user_data.get("selected", {})
    teks_ring, total = ringkasan_items(selected)
    keyboard = [
        [InlineKeyboardButton("✅ Simpan", callback_data="simpan")],
        [InlineKeyboardButton("❌ Batal", callback_data="batal")],
    ]
    await query.edit_message_text(
        f"📋 *Konfirmasi Penjualan:*\n\n{teks_ring}\n💳 Pembayaran: {pembayaran}\n\nSudah benar?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return KONFIRMASI

async def simpan_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    username = f"@{user.username}" if user.username else user.first_name
    selected = context.user_data.get("selected", {})
    pembayaran = context.user_data.get("pembayaran", "-")

    items = []
    for key, jumlah in selected.items():
        if jumlah > 0:
            produk = MENU[key]
            items.append({
                "nama": produk["nama"],
                "jumlah": jumlah,
                "harga_satuan": produk["harga"],
                "total": produk["harga"] * jumlah,
            })

    try:
        simpan_ke_sheet(items, pembayaran, username)
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
        keyboard = [[InlineKeyboardButton("🏠 Menu Utama", callback_data="menu_utama")]]
        await query.edit_message_text(
            f"❌ Gagal menyimpan: {str(e)}\n\nTekan Menu Utama untuk coba lagi.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    context.user_data.clear()
    return ConversationHandler.END

async def rekap_hari_ini(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        result = get_rekap_hari_ini()
        today = datetime.now(WIB).strftime("%d/%m/%Y")
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
        keyboard = [[InlineKeyboardButton("🏠 Menu Utama", callback_data="menu_utama")]]
        await query.edit_message_text(
            f"❌ Gagal mengambil rekap: {str(e)}\n\nTekan Menu Utama untuk coba lagi.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
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
            PILIH_PRODUK: [
                CallbackQueryHandler(pilih_produk, pattern="^pilih_"),
                CallbackQueryHandler(pilih_jumlah_produk, pattern="^jumlah_"),
                CallbackQueryHandler(reset_pilihan, pattern="^reset_pilihan$"),
                CallbackQueryHandler(lanjut_bayar, pattern="^lanjut_bayar$"),
            ],
            PILIH_BAYAR: [
                CallbackQueryHandler(pilih_bayar, pattern="^(qris|cash)$"),
            ],
            KONFIRMASI: [
                CallbackQueryHandler(simpan_data, pattern="^simpan$"),
            ],
        },
        fallbacks=[
            CallbackQueryHandler(batal, pattern="^batal$"),
            CallbackQueryHandler(menu_utama_cb, pattern="^menu_utama$"),
            CommandHandler("start", start),
        ],
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
