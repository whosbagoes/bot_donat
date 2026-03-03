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

# Daftar Menu Lengkap
MENU = {
    "paket_teman_dekat": {"nama": "Paket Teman Dekat", "harga": 40000, "emoji": "🍩❤️"},
    "paket_teman_manis": {"nama": "Paket Teman Manis", "harga": 20000, "emoji": "🍩🌸"},
    "donat_pcs":         {"nama": "Donat PCS",          "harga": 7000,  "emoji": "🍩"},
    "crackbite":         {"nama": "Crackbite",          "harga": 10000, "emoji": "🍪✨"},
    "cheesedream":       {"nama": "Cheesedream",        "harga": 15000, "emoji": "🧀☁️"},
    "peanut_butter":     {"nama": "Peanut Butter",      "harga": 10000, "emoji": "🥜🤎"},
    "ichigo_c":          {"nama": "Ichigo C",           "harga": 14000, "emoji": "🍓🍫"},
    "choco_c":           {"nama": "Choco C",            "harga": 14000, "emoji": "🍫🍩"},
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

def simpan_ke_sheet(items: list, pembayaran: str):
    sheet = get_sheet()
    rows = sheet.get_all_values()
    no = len(rows)
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
    return now.strftime("%H:%M:%S")

def ambil_riwayat_terakhir(limit=5):
    try:
        sheet = get_sheet()
        rows = sheet.get_all_values()
        if len(rows) <= 1:
            return "Belum ada transaksi."
        
        recent_rows = rows[1:][-15:] 
        riwayat = []
        last_time = ""
        count = 0
        
        for row in reversed(recent_rows):
            time_str = row[2]
            if time_str != last_time:
                riwayat.append(f"⏰ `{time_str}` - {row[3]} ({row[7]})")
                last_time = time_str
                count += 1
            if count >= limit:
                break
                
        return "\n".join(riwayat)
    except Exception as e:
        return f"Gagal ambil riwayat: {str(e)}"

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

# ==================== KEYBOARD GRID VERSION ====================
def build_menu_keyboard(selected: dict):
    keyboard = []
    total_semua = 0
    menu_list = list(MENU.items())

    # Membuat baris produk (2 produk per baris)
    for i in range(0, len(menu_list), 2):
        row_items = menu_list[i:i+2]
        buttons = []
        for key, produk in row_items:
            jumlah = selected.get(key, 0)
            total_semua += produk["harga"] * jumlah
            
            # Jika dipilih, tampilkan tanda ✅ dan jumlahnya
            label = f"{produk['emoji']} {produk['nama']}"
            if jumlah > 0:
                label = f"✅ {jumlah}x {produk['nama']}"
            
            buttons.append(InlineKeyboardButton(label, callback_data=f"plus_{key}"))
        keyboard.append(buttons)

        # Tambahkan baris tombol minus hanya untuk produk di baris ini yang sudah dipilih
        minus_buttons = []
        for key, produk in row_items:
            if selected.get(key, 0) > 0:
                minus_buttons.append(InlineKeyboardButton(f"➖ {produk['nama']}", callback_data=f"minus_{key}"))
        if minus_buttons:
            keyboard.append(minus_buttons)

    # Tombol Aksi di bagian paling bawah
    if total_semua > 0:
        keyboard.append([InlineKeyboardButton(f"➡️ BAYAR: Rp {fmt(total_semua)}", callback_data="lanjut_bayar")])
        keyboard.append([InlineKeyboardButton("🗑 Reset Pilihan", callback_data="reset_pilihan")])
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
        [InlineKeyboardButton("📜 5 Transaksi Terakhir", callback_data="riwayat")],
        [InlineKeyboardButton("🗑 Hapus Terakhir", callback_data="hapus_terakhir")],
    ]
    text = "🍩 *Bot Penjualan Donat*\n\nHalo! Mau ngapain?"
    if update.message:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    else:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def menu_utama_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    await start(update, context)

async def lihat_riwayat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    riwayat = ambil_riwayat_terakhir()
    keyboard = [[InlineKeyboardButton("🏠 Menu Utama", callback_data="menu_utama")]]
    await query.edit_message_text(
        f"📜 *Riwayat Terakhir:*\n\n{riwayat}\n\n_Cek ini untuk memastikan data sudah masuk._",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def catat_penjualan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["selected"] = {}
    await query.edit_message_text(
        "🍩 *Pilih Produk:*\n\nKlik nama untuk tambah, ➖ untuk kurangi.",
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
        "🍩 *Pilih Produk:*\n\nKlik nama untuk tambah, ➖ untuk kurangi.",
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
        "🍩 *Pilih Produk:*\n\nKlik nama untuk tambah, ➖ untuk kurangi.",
        reply_markup=build_menu_keyboard(selected),
        parse_mode="Markdown"
    )
    return PILIH_PRODUK

async def reset_pilihan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["selected"] = {}
    await query.edit_message_text(
        "🍩 *Pilih Produk:*",
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
        [InlineKeyboardButton("QRIS 📱", callback_data="qris"), InlineKeyboardButton("Cash 💵", callback_data="cash")],
        [InlineKeyboardButton("⬅️ Ubah Pesanan", callback_data="catat")],
    ]
    await query.edit_message_text(
        f"🛒 *Ringkasan Pesanan:*\n{teks}\n*Total: Rp {fmt(total)}*\n\nPilih pembayaran:",
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
        [InlineKeyboardButton("✅ SIMPAN DATA", callback_data="simpan")],
        [InlineKeyboardButton("⬅️ Kembali", callback_data="catat")],
    ]
    await query.edit_message_text(
        f"📋 *Konfirmasi Akhir:*\n\n{teks}\n💳 {context.user_data['pembayaran']}\n\nSudah sesuai?",
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
        waktu = simpan_ke_sheet(items, pembayaran)
        keyboard = [[InlineKeyboardButton("🛒 Catat Lagi", callback_data="catat")], [InlineKeyboardButton("🏠 Menu Utama", callback_data="menu_utama")]]
        await query.edit_message_text(
            f"✅ *Berhasil Disimpan!*\n⏰ Jam: `{waktu}`\n\n_Data sudah masuk ke Google Sheets._",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error: {e}")
        await query.edit_message_text(f"❌ Gagal simpan: {e}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="menu_utama")]]))
    
    context.user_data.clear()
    return ConversationHandler.END

async def hapus_terakhir(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [[InlineKeyboardButton("✅ Ya, Hapus", callback_data="konfirm_hapus")], [InlineKeyboardButton("❌ Batal", callback_data="menu_utama")]]
    await query.edit_message_text("⚠️ Hapus transaksi terakhir yang baru saja masuk?", reply_markup=InlineKeyboardMarkup(keyboard))

async def konfirm_hapus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ok, hasil = hapus_transaksi_terakhir()
    msg = f"✅ Berhasil dihapus ({hasil} baris)." if ok else f"❌ {hasil}"
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="menu_utama")]]))

async def batal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    await start(update, context)
    return ConversationHandler.END

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
        fallbacks=[CallbackQueryHandler(batal, pattern="^batal$"), CallbackQueryHandler(menu_utama_cb, pattern="^menu_utama$")],
        per_message=False,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(lihat_riwayat, pattern="^riwayat$"))
    app.add_handler(CallbackQueryHandler(hapus_terakhir, pattern="^hapus_terakhir$"))
    app.add_handler(CallbackQueryHandler(konfirm_hapus, pattern="^konfirm_hapus$"))
    app.add_handler(CallbackQueryHandler(menu_utama_cb, pattern="^menu_utama$"))

    logger.info("🍩 Bot Donat Berjalan...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
