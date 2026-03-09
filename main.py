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
    "paket_teman_dekat": {"nama": "Paket Teman Dekat", "harga": 40000},
    "paket_teman_manis": {"nama": "Paket Teman Manis", "harga": 20000},
    "donat_pcs":         {"nama": "Donat PCS",          "harga": 7000 },
    "crackbite":         {"nama": "Crackbite",          "harga": 10000},
    "cheesedream":       {"nama": "Cheesedream",        "harga": 15000},
    "peanut_butter":     {"nama": "Peanut Butter",      "harga": 10000},
    "ichigo_c":          {"nama": "Ichigo C",           "harga": 14000},
    "choco_c":           {"nama": "Choco C",            "harga": 14000},
    "garlic_butter":     {"nama": "Garlic Butter",      "harga": 14000},
    "beef_pizza":        {"nama": "Beef Pizza",         "harga": 14000},
    "beef_mentai":       {"nama": "Beef Mentai",        "harga": 14000},
    "bombo":             {"nama": "Bombo",               "harga": 10000},
}

PEMBAYARAN = {
    "qris": "QRIS 📱",
    "cash": "Cash 💵",
}

PILIH_PRODUK, PILIH_BAYAR, INPUT_DISKON, KONFIRMASI = range(4)

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ==================== GOOGLE SHEETS ====================
def get_sheet():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds_json = json.loads(os.environ.get("GOOGLE_CREDENTIALS"))
    spreadsheet_id = os.environ.get("SPREADSHEET_ID")
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_json, scope)
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(spreadsheet_id)
    try:
        sheet = spreadsheet.worksheet(SHEET_NAME)
    except gspread.WorksheetNotFound:
        sheet = spreadsheet.add_worksheet(title=SHEET_NAME, rows=1000, cols=8)
        sheet.append_row(["No", "Tanggal", "Waktu", "Produk", "Jumlah", "Harga Satuan", "Total", "Metode Bayar", "Diskon"])
    return sheet

def simpan_ke_sheet(items: list, pembayaran: str, diskon: int = 0):
    sheet = get_sheet()
    rows = sheet.get_all_values()
    no = len(rows)
    now = datetime.now(WIB)
    for i, item in enumerate(items):
        diskon_row = diskon if i == 0 else 0  # tulis diskon hanya di baris pertama
        sheet.append_row([no, now.strftime("%d/%m/%Y"), now.strftime("%H:%M:%S"), item["nama"], item["jumlah"], item["harga_satuan"], item["total"], pembayaran, diskon_row])
        no += 1
    return now.strftime("%H:%M:%S")

def ambil_riwayat_terakhir(limit=5):
    try:
        sheet = get_sheet()
        rows = sheet.get_all_values()
        if len(rows) <= 1: return "Belum ada transaksi."
        recent_rows = rows[1:][-15:] 
        riwayat, last_time, count = [], "", 0
        for row in reversed(recent_rows):
            if row[2] != last_time:
                riwayat.append(f"⏰ `{row[2]}` - {row[3]} ({row[7]})")
                last_time, count = row[2], count + 1
            if count >= limit: break
        return "\n".join(riwayat)
    except: return "Gagal ambil riwayat."

def hapus_transaksi_terakhir():
    sheet = get_sheet()
    rows = sheet.get_all_values()
    if len(rows) <= 1: return False, "Kosong."
    last_time = rows[-1][2]
    deleted = 0
    for i in range(len(rows) - 1, 0, -1):
        if rows[i][2] == last_time:
            sheet.delete_rows(i + 1)
            deleted += 1
        else: break
    return True, deleted

def fmt(angka):
    return f"{int(angka):,}".replace(",", ".")

# ==================== KEYBOARD GRID OPTIMIZED ====================
def build_menu_keyboard(selected: dict):
    keyboard = []
    total_semua = 0
    menu_list = list(MENU.items())

    # Grid 2 Kolom
    for i in range(0, len(menu_list), 2):
        row_items = menu_list[i:i+2]
        buttons = []
        for key, produk in row_items:
            jumlah = selected.get(key, 0)
            total_semua += produk["harga"] * jumlah
            label = produk["nama"]
            if jumlah > 0: label = f"✅ {jumlah}x {produk['nama']}"
            buttons.append(InlineKeyboardButton(label, callback_data=f"plus_{key}"))
        keyboard.append(buttons)

        # Tombol Minus (Muncul hanya jika ada produk yang dipilih di baris ini)
        minus_buttons = []
        for key, produk in row_items:
            if selected.get(key, 0) > 0:
                minus_buttons.append(InlineKeyboardButton(f"❌ Kurangi {produk['nama']}", callback_data=f"minus_{key}"))
        if minus_buttons:
            keyboard.append(minus_buttons)

    if total_semua > 0:
        keyboard.append([InlineKeyboardButton(f"➡️ BAYAR SEKARANG: Rp {fmt(total_semua)}", callback_data="lanjut_bayar")])
        keyboard.append([InlineKeyboardButton("🗑️ Reset Semua", callback_data="reset_pilihan")])
    else:
        keyboard.append([InlineKeyboardButton("⬅️ Kembali ke Menu Utama", callback_data="batal")])
        
    return InlineKeyboardMarkup(keyboard)

# ==================== HANDLERS ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🛒 Catat Penjualan Baru", callback_data="catat")],
        [InlineKeyboardButton("📜 Cek Riwayat Terakhir", callback_data="riwayat")],
        [InlineKeyboardButton("🗑️ Hapus Salah Input", callback_data="hapus_terakhir")],
    ]
    text = "🍩 *Kasir Donat*\n\nSiap melayani pembeli!"
    if update.message:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    else:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def catat_penjualan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["selected"] = {}
    await query.edit_message_text("🍩 *Pilih Pesanan:*", reply_markup=build_menu_keyboard({}), parse_mode="Markdown")
    return PILIH_PRODUK

async def plus_produk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    key = query.data.replace("plus_", "")
    selected = context.user_data.get("selected", {})
    selected[key] = selected.get(key, 0) + 1
    context.user_data["selected"] = selected
    await query.edit_message_text("🍩 *Pilih Pesanan:*", reply_markup=build_menu_keyboard(selected), parse_mode="Markdown")
    return PILIH_PRODUK

async def minus_produk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    key = query.data.replace("minus_", "")
    selected = context.user_data.get("selected", {})
    selected[key] = max(0, selected.get(key, 0) - 1)
    context.user_data["selected"] = selected
    await query.edit_message_text("🍩 *Pilih Pesanan:*", reply_markup=build_menu_keyboard(selected), parse_mode="Markdown")
    return PILIH_PRODUK

async def lanjut_bayar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    teks, total, _ = ringkasan_items(context.user_data.get("selected", {}))
    diskon = context.user_data.get("diskon", 0)
    total_bayar = max(0, total - diskon)
    diskon_info = f"\n🏷️ Diskon: -Rp {fmt(diskon)}\n*Total Bayar: Rp {fmt(total_bayar)}*" if diskon > 0 else f"\n*Total: Rp {fmt(total)}*"
    keyboard = [
        [InlineKeyboardButton("🏷️ Tambah/Edit Diskon", callback_data="input_diskon")],
        [InlineKeyboardButton("QRIS 📱", callback_data="qris"), InlineKeyboardButton("Cash 💵", callback_data="cash")],
        [InlineKeyboardButton("⬅️ Edit Pesanan", callback_data="catat")]
    ]
    await query.edit_message_text(f"🛒 *Ringkasan:*\n{teks}{diskon_info}\n\nPilih cara bayar:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    return PILIH_BAYAR

async def minta_input_diskon(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [[InlineKeyboardButton("⬅️ Kembali", callback_data="batal_diskon")]]
    await query.edit_message_text("🏷️ *Masukkan nominal diskon (angka saja):*\nContoh: `5000`", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    return INPUT_DISKON

async def batal_diskon(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    teks, total, _ = ringkasan_items(context.user_data.get("selected", {}))
    diskon = context.user_data.get("diskon", 0)
    total_bayar = max(0, total - diskon)
    diskon_info = f"\n🏷️ Diskon: -Rp {fmt(diskon)}\n*Total Bayar: Rp {fmt(total_bayar)}*" if diskon > 0 else f"\n*Total: Rp {fmt(total)}*"
    keyboard = [
        [InlineKeyboardButton("🏷️ Tambah/Edit Diskon", callback_data="input_diskon")],
        [InlineKeyboardButton("QRIS 📱", callback_data="qris"), InlineKeyboardButton("Cash 💵", callback_data="cash")],
        [InlineKeyboardButton("⬅️ Edit Pesanan", callback_data="catat")]
    ]
    await query.edit_message_text(f"🛒 *Ringkasan:*\n{teks}{diskon_info}\n\nPilih cara bayar:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    return PILIH_BAYAR

async def terima_diskon(update: Update, context: ContextTypes.DEFAULT_TYPE):
    teks = update.message.text.strip().replace(".", "").replace(",", "")
    try:
        diskon = int(teks)
        if diskon < 0:
            raise ValueError
        context.user_data["diskon"] = diskon
        # Kirim pesan sementara lalu tampilkan ulang ringkasan
        teks_ringkasan, total, _ = ringkasan_items(context.user_data.get("selected", {}))
        total_bayar = max(0, total - diskon)
        diskon_info = f"\n🏷️ Diskon: -Rp {fmt(diskon)}\n*Total Bayar: Rp {fmt(total_bayar)}*"
        keyboard = [
            [InlineKeyboardButton("🏷️ Tambah/Edit Diskon", callback_data="input_diskon")],
            [InlineKeyboardButton("QRIS 📱", callback_data="qris"), InlineKeyboardButton("Cash 💵", callback_data="cash")],
            [InlineKeyboardButton("⬅️ Edit Pesanan", callback_data="catat")]
        ]
        await update.message.reply_text(f"🛒 *Ringkasan:*\n{teks_ringkasan}{diskon_info}\n\nPilih cara bayar:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        return PILIH_BAYAR
    except ValueError:
        await update.message.reply_text("❌ Input tidak valid. Masukkan angka saja, contoh: `5000`", parse_mode="Markdown")
        return INPUT_DISKON

async def pilih_bayar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["pembayaran"] = PEMBAYARAN[query.data]
    teks, _, _ = ringkasan_items(context.user_data.get("selected", {}))
    keyboard = [[InlineKeyboardButton("✅ SIMPAN & SELESAI", callback_data="simpan")], [InlineKeyboardButton("⬅️ Ganti Pesanan", callback_data="catat")]]
    diskon = context.user_data.get("diskon", 0)
    _, total, _ = ringkasan_items(context.user_data.get("selected", {}))
    total_bayar = max(0, total - diskon)
    diskon_info = f"🏷️ Diskon: -Rp {fmt(diskon)}\n" if diskon > 0 else ""
    await query.edit_message_text(f"📋 *Konfirmasi:*\n\n{teks}\n{diskon_info}💳 Bayar: {context.user_data['pembayaran']}\n*Total Bayar: Rp {fmt(total_bayar)}*\n\nSimpan sekarang?", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    return KONFIRMASI

async def simpan_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, _, items = ringkasan_items(context.user_data.get("selected", {}))
    try:
        diskon = context.user_data.get("diskon", 0)
        waktu = simpan_ke_sheet(items, context.user_data.get("pembayaran", "-"), diskon)
        await query.edit_message_text(f"✅ *Sukses Dicatat!*\n⏰ Jam: `{waktu}`", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🛒 Transaksi Baru", callback_data="catat")], [InlineKeyboardButton("🏠 Home", callback_data="menu_utama")]]), parse_mode="Markdown")
    except Exception as e:
        await query.edit_message_text(f"❌ Error: {e}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Home", callback_data="menu_utama")]]))
    context.user_data.clear()
    return ConversationHandler.END

def ringkasan_items(selected: dict):
    teks, total, items = "", 0, []
    for key, jumlah in selected.items():
        if jumlah > 0:
            p = MENU[key]
            sub = p["harga"] * jumlah
            total += sub
            teks += f"• {p['nama']} x{jumlah} = Rp {fmt(sub)}\n"
            items.append({"nama": p["nama"], "jumlah": jumlah, "harga_satuan": p["harga"], "total": sub})
    return teks, total, items

async def lihat_riwayat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    riwayat = ambil_riwayat_terakhir()
    await query.edit_message_text(f"📜 *Riwayat:* \n\n{riwayat}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Home", callback_data="menu_utama")]]), parse_mode="Markdown")

async def hapus_terakhir(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("⚠️ Hapus data terakhir?", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Ya", callback_data="konfirm_hapus"), InlineKeyboardButton("❌ Tidak", callback_data="menu_utama")]]))

async def konfirm_hapus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ok, hasil = hapus_transaksi_terakhir()
    msg = f"✅ Terhapus ({hasil} baris)." if ok else f"❌ {hasil}"
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Home", callback_data="menu_utama")]]))

async def menu_utama_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    await start(update, context)

async def batal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    await start(update, context)
    return ConversationHandler.END

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(catat_penjualan, pattern="^catat$")],
        states={
            PILIH_PRODUK: [CallbackQueryHandler(plus_produk, pattern="^plus_"), CallbackQueryHandler(minus_produk, pattern="^minus_"), CallbackQueryHandler(lanjut_bayar, pattern="^lanjut_bayar$"), CallbackQueryHandler(catat_penjualan, pattern="^reset_pilihan$")],
            PILIH_BAYAR: [CallbackQueryHandler(minta_input_diskon, pattern="^input_diskon$"), CallbackQueryHandler(pilih_bayar, pattern="^(qris|cash)$"), CallbackQueryHandler(catat_penjualan, pattern="^catat$")],
            INPUT_DISKON: [CallbackQueryHandler(batal_diskon, pattern="^batal_diskon$"), MessageHandler(filters.TEXT & ~filters.COMMAND, terima_diskon)],
            KONFIRMASI: [CallbackQueryHandler(simpan_data, pattern="^simpan$"), CallbackQueryHandler(catat_penjualan, pattern="^catat$")],
        },
        fallbacks=[CallbackQueryHandler(batal, pattern="^batal$"), CallbackQueryHandler(menu_utama_cb, pattern="^menu_utama$")],
        per_message=False,
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(lihat_riwayat, pattern="^riwayat$"))
    app.add_handler(CallbackQueryHandler(hapus_terakhir, pattern="^hapus_terakhir$"))
    app.add_handler(CallbackQueryHandler(konfirm_hapus, pattern="^konfirm_hapus$"))
    app.add_handler(CallbackQueryHandler(menu_utama_cb, pattern="^menu_utama$"))
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()