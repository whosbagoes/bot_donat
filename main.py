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

MENU = {
    "paket_teman_dekat": {"nama": "Paket Teman Dekat", "harga": 40000, "emoji": "🍩❤️"},
    "paket_teman_manis": {"nama": "Paket Teman Manis", "harga": 20000, "emoji": "🍩🌸"},
    "donat_pcs":         {"nama": "Donat PCS",          "harga": 7000,  "emoji": "🍩"},
    "crackbite":         {"nama": "Crackbite",          "harga": 10000, "emoji": "🍪✨"}, # Produk Baru
}

PEMBAYARAN = {
    "qris": "QRIS 📱",
    "cash": "Cash 💵",
}

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
        sheet = spreadsheet.add_worksheet(title=SHEET_NAME, rows=1000, cols=8)
        sheet.append_row(["No", "Tanggal", "Waktu", "Produk", "Jumlah", "Harga Satuan", "Total", "Metode Bayar"])
    return sheet

def parse_angka(nilai):
    if not nilai:
        return 0
    nilai = str(nilai).replace("Rp", "").replace(",", "").replace(".", "").strip()
    try:
        return int(float(nilai))
    except:
        return 0

def simpan_ke_sheet(items: list, pembayaran: str):
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
        ])
        no += 1

def hapus_transaksi_terakhir():
    sheet = get_sheet()
    rows = sheet.get_all_values()
    if len(rows) <= 1:
        return False, "Tidak ada data yang bisa dihapus."
    last_time = rows[-1][2]
    deleted = 0
    for i in range(len(rows) - 1, 0, -1):
        if rows[i][2] == last_time:
            sheet.delete_rows(i + 1)
            deleted += 1
        else:
            break
    return True, deleted

def fmt(angka):
    return f"{int(angka):,}".replace(",", ".")

# ==================== KEYBOARD ====================
def build_menu_keyboard(selected: dict):
    keyboard = []
    total_semua = 0
    for key, produk in MENU.items():
        jumlah = selected.get(key, 0)
        total_semua += produk["harga"] * jumlah
        keyboard.append([InlineKeyboardButton(
            f"{produk['emoji']} {produk['nama']} (Rp {fmt(produk['harga'])})",
            callback_data="noop"
        )])
        if jumlah == 0:
            keyboard.append([InlineKeyboardButton("➕ Tambah", callback_data=f"plus_{key}")])
        else:
            keyboard.append([
                InlineKeyboardButton("➖", callback_data=f"minus_{key}"),
                InlineKeyboardButton(f"  {jumlah}  ", callback_data="noop"),
                InlineKeyboardButton("➕", callback_data=f"plus_{key}"),
            ])

    if total_semua > 0:
        keyboard.append([InlineKeyboardButton("🗑 Reset", callback_data="reset_pilihan")])
        keyboard.append([InlineKeyboardButton(f"➡️ Bayar — Rp {fmt(total_semua)}", callback_data="lanjut_bayar")])
    else:
        keyboard.append([InlineKeyboardButton("❌ Batal", callback_data="batal")])
    return InlineKeyboardMarkup(keyboard)

def ringkasan_items(selected: dict):
    teks = ""
    total = 0
    items = []
    for key, jumlah in selected.items():
        if jumlah > 0:
            produk = MENU[key]
            subtotal = produk["harga"] * jumlah
            total += subtotal
            teks += f"  {produk['emoji']} {produk['nama']} x{jumlah} = Rp {fmt(subtotal)}\n"
            items.append({
                "nama": produk["nama"],
                "jumlah": jumlah,
                "harga_satuan": produk["harga"],
                "total": subtotal,
            })
    return teks, total, items

# ==================== HANDLERS ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🛒 Catat Penjualan", callback_data="catat")],
        [InlineKeyboardButton("🗑 Hapus Transaksi Terakhir", callback_data="hapus_terakhir")],
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
        [InlineKeyboardButton("🗑 Hapus Transaksi Terakhir", callback_data="hapus_terakhir")],
    ]
    await query.edit_message_text(
        "🍩 *Bot Penjualan Donat*\n\nMau ngapain?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def catat_penjualan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["selected"] = {}
    await query.edit_message_text(
        "🍩 *Pilih Produk:*\n\nTap ➕ untuk tambah, ➖ untuk kurangi.",
        reply_markup=build_menu_keyboard({}),
        parse_mode="Markdown"
    )
    return PILIH_PRODUK

async def plus_produk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    key = query.data.replace("plus_", "")
    selected = context.user_data.get("selected", {})
    selected[key] = selected.get(key, 0) + 1
    context.user_data["selected"] = selected
    await query.edit_message_text(
        "🍩 *Pilih Produk:*\n\nTap ➕ untuk tambah, ➖ untuk kurangi.",
        reply_markup=build_menu_keyboard(selected),
        parse_mode="Markdown"
    )
    return PILIH_PRODUK

async def minus_produk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    key = query.data.replace("minus_", "")
    selected = context.user_data.get("selected", {})
    selected[key] = max(0, selected.get(key, 0) - 1)
    context.user_data["selected"] = selected
    await query.edit_message_text(
        "🍩 *Pilih Produk:*\n\nTap ➕ untuk tambah, ➖ untuk kurangi.",
        reply_markup=build_menu_keyboard(selected),
        parse_mode="Markdown"
    )
    return PILIH_PRODUK

async def reset_pilihan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["selected"] = {}
    await query.edit_message_text(
        "🍩 *Pilih Produk:*\n\nTap ➕ untuk tambah, ➖ untuk kurangi.",
        reply_markup=build_menu_keyboard({}),
        parse_mode="Markdown"
    )
    return PILIH_PRODUK

async def lanjut_bayar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    selected = context.user_data.get("selected", {})
    teks, total, _ = ringkasan_items(selected)
    keyboard = [
        [
            InlineKeyboardButton("QRIS 📱", callback_data="qris"),
            InlineKeyboardButton("Cash 💵", callback_data="cash"),
        ],
        [InlineKeyboardButton("⬅️ Ubah Pesanan", callback_data="catat")],
    ]
    await query.edit_message_text(
        f"🛒 *Pesanan:*\n{teks}\nPilih *metode pembayaran:*",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return PILIH_BAYAR

async def pilih_bayar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["pembayaran"] = PEMBAYARAN[query.data]
    selected = context.user_data.get("selected", {})
    teks, total, _ = ringkasan_items(selected)
    keyboard = [
        [InlineKeyboardButton("✅ Simpan", callback_data="simpan")],
        [InlineKeyboardButton("⬅️ Ubah Pesanan", callback_data="catat")],
    ]
    await query.edit_message_text(
        f"📋 *Konfirmasi:*\n\n{teks}\n💳 {context.user_data['pembayaran']}\n\nSudah benar?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return KONFIRMASI

async def simpan_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    selected = context.user_data.get("selected", {})
    pembayaran = context.user_data.get("pembayaran", "-")
    _, _, items = ringkasan_items(selected)
    try:
        simpan_ke_sheet(items, pembayaran)
        keyboard = [
            [InlineKeyboardButton("🛒 Catat Lagi", callback_data="catat")],
            [InlineKeyboardButton("🏠 Menu Utama", callback_data="menu_utama")],
        ]
        await query.edit_message_text(
            "✅ *Penjualan berhasil dicatat!* 📊",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error simpan: {e}")
        keyboard = [[InlineKeyboardButton("🏠 Menu Utama", callback_data="menu_utama")]]
        await query.edit_message_text(
            f"❌ Gagal menyimpan: {str(e)}",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    context.user_data.clear()
    return ConversationHandler.END

async def hapus_terakhir(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [
        [
            InlineKeyboardButton("✅ Ya, Hapus", callback_data="konfirm_hapus"),
            InlineKeyboardButton("❌ Batal", callback_data="menu_utama"),
        ]
    ]
    await query.edit_message_text(
        "⚠️ Yakin mau hapus transaksi terakhir?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def konfirm_hapus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        ok, hasil = hapus_transaksi_terakhir()
        keyboard = [[InlineKeyboardButton("🏠 Menu Utama", callback_data="menu_utama")]]
        if ok:
            await query.edit_message_text(
                f"✅ Transaksi terakhir berhasil dihapus ({hasil} baris).",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            await query.edit_message_text(f"❌ {hasil}", reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception as e:
        logger.error(f"Error hapus: {e}")
        keyboard = [[InlineKeyboardButton("🏠 Menu Utama", callback_data="menu_utama")]]
        await query.edit_message_text(f"❌ Gagal menghapus: {str(e)}", reply_markup=InlineKeyboardMarkup(keyboard))

async def batal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    keyboard = [[InlineKeyboardButton("🏠 Menu Utama", callback_data="menu_utama")]]
    await query.edit_message_text("❌ Dibatalkan.", reply_markup=InlineKeyboardMarkup(keyboard))
    return ConversationHandler.END

async def noop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()

# ==================== MAIN ====================
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(catat_penjualan, pattern="^catat$")],
        states={
            PILIH_PRODUK: [
                CallbackQueryHandler(plus_produk, pattern="^plus_"),
                CallbackQueryHandler(minus_produk, pattern="^minus_"),
                CallbackQueryHandler(reset_pilihan, pattern="^reset_pilihan$"),
                CallbackQueryHandler(lanjut_bayar, pattern="^lanjut_bayar$"),
                CallbackQueryHandler(noop, pattern="^noop$"),
            ],
            PILIH_BAYAR: [
                CallbackQueryHandler(pilih_bayar, pattern="^(qris|cash)$"),
                CallbackQueryHandler(catat_penjualan, pattern="^catat$"),
            ],
            KONFIRMASI: [
                CallbackQueryHandler(simpan_data, pattern="^simpan$"),
                CallbackQueryHandler(catat_penjualan, pattern="^catat$"),
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
    app.add_handler(CallbackQueryHandler(hapus_terakhir, pattern="^hapus_terakhir$"))
    app.add_handler(CallbackQueryHandler(konfirm_hapus, pattern="^konfirm_hapus$"))
    app.add_handler(CallbackQueryHandler(noop, pattern="^noop$"))

    logger.info("🍩 Bot Donat berjalan...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
