import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, InputFile
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    ContextTypes
)
import aiohttp
import asyncio
import os
from datetime import datetime, timedelta

# Konfigurasi
ADMIN_IDS = [7172158541]  # Ganti dengan ID Telegram admin
MAX_MESSAGE_AGE = 3  # Detik
MIHOMO_API = 'http://127.0.0.1:9090'
API_SECRET = '123456'  # Ganti dengan secret yang benar
BOT_TOKEN = '7941020551:AAEeTfmgQ0UURyEUuueNd4ZaA3j3fB_0TOM'  # Ganti dengan token bot Anda
HEADERS = {'Authorization': f'Bearer {API_SECRET}'}
IP_CHECK_INTERVAL = 300  # 5 menit
REQUEST_TIMEOUT = 10  # Timeout untuk request API

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Global cache IP publik
current_ip = None
last_ip_check = None

class APIError(Exception):
    """Custom exception untuk error API"""
    pass

async def is_admin(user_id: int) -> bool:
    """Cek apakah user adalah admin"""
    return user_id in ADMIN_IDS

async def make_api_request(method: str, endpoint: str, **kwargs) -> dict:
    """Helper function untuk membuat request ke API Mihomo"""
    url = f"{MIHOMO_API}{endpoint}"
    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
    
    try:
        async with aiohttp.ClientSession(headers=HEADERS, timeout=timeout) as session:
            async with session.request(method, url, **kwargs) as response:
                if response.status != 200:
                    raise APIError(f"API returned status {response.status}")
                return await response.json()
    except asyncio.TimeoutError:
        raise APIError("Request timeout")
    except Exception as e:
        raise APIError(f"API request failed: {str(e)}")

async def notify_admins(app):
    """Memberi notifikasi ke admin saat bot aktif"""
    for admin_id in ADMIN_IDS:
        try:
            await app.bot.send_message(
                chat_id=admin_id,
                text="✅ Bot Mihomo aktif dan siap digunakan."
            )
        except Exception as e:
            logger.error(f"Gagal mengirim notifikasi ke admin {admin_id}: {e}")
    
    # Mulai monitor IP
    asyncio.create_task(ip_monitor(app))

def main_menu_keyboard(proxies: dict) -> InlineKeyboardMarkup:
    """Membuat keyboard menu utama"""
    selector_buttons = [
        InlineKeyboardButton(
            f"{name} ➜ {proxies[name].get('now', '?')}", 
            callback_data=f"select_{name}"
        )
        for name in proxies if proxies[name]['type'] == 'Selector'
    ]
    
    # Atur 2 tombol per baris
    keyboard = [selector_buttons[i:i+2] for i in range(0, len(selector_buttons), 2)]
    
    # Tambahkan tombol aksi
    keyboard += [
        [InlineKeyboardButton("🔄 Status Delay", callback_data="status"),
         InlineKeyboardButton("⚡ Proxy Tercepat", callback_data="fastest")],
        [InlineKeyboardButton("🌐 Lihat IP Publik", callback_data="ip"),
         InlineKeyboardButton("ℹ️ Versi", callback_data="version")],
        [InlineKeyboardButton("🔄 Reload Config", callback_data="reload"),
         InlineKeyboardButton("🔄 Restart Clash", callback_data="restart")],
        [InlineKeyboardButton("💾 Backup Config", callback_data="backup")]
    ]
    
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk command /start"""
    user_id = update.effective_user.id
    msg_time = update.message.date.timestamp()
    
    # Validasi pesan dan admin
    if time.time() - msg_time > MAX_MESSAGE_AGE:
        return await update.message.reply_text("⚠️ Pesan sudah kedaluwarsa.")
    
    if not await is_admin(user_id):
        return await update.message.reply_text("⛔ Akses ditolak. Hanya admin yang diizinkan.")
    
    try:
        proxies = await make_api_request('GET', '/proxies')
        await update.message.reply_text(
            "📋 Pilih grup proxy atau perintah:",
            reply_markup=main_menu_keyboard(proxies['proxies'])
        )
    except APIError as e:
        logger.error(f"Error getting proxies: {e}")
        await update.message.reply_text("❌ Gagal memuat daftar proxy. Coba lagi nanti.")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk semua callback query"""
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    
    # Validasi admin
    if not await is_admin(user_id):
        return
    
    # Validasi waktu tombol
    if (datetime.now() - query.message.date) > timedelta(minutes=5):
        return await query.answer("⚠️ Tombol sudah kedaluwarsa.", show_alert=True)
    
    data = query.data
    
    try:
        if data.startswith("select_"):
            await handle_proxy_selection(query, data)
        elif data.startswith("choose_"):
            await handle_proxy_choice(query, data)
        elif data == "status":
            await handle_status_check(query)
        elif data == "ip":
            await handle_ip_check(query)
        elif data == "fastest":
            await handle_fastest_proxy(query)
        elif data == "reload":
            await handle_reload_config(query)
        elif data == "restart":
            await handle_restart(query)
        elif data == "version":
            await handle_version_check(query)
        elif data == "backup":
            await handle_backup(query)
        elif data == "back":
            await handle_back_to_menu(query)
            
    except APIError as e:
        logger.error(f"API Error in button handler: {e}")
        await query.edit_message_text(f"❌ Error: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error in button handler: {e}")
        await query.edit_message_text("❌ Terjadi kesalahan tak terduga.")

async def handle_proxy_selection(query, data):
    """Handle pemilihan grup proxy"""
    group = data.split("_", 1)[1]
    group_info = await make_api_request('GET', f'/proxies/{group}')
    now = group_info.get('now', 'Tidak diketahui')
    
    buttons = [
        InlineKeyboardButton(
            f"{'⭐ ' if p == now else ''}{p}", 
            callback_data=f"choose_{group}_{p}"
        ) for p in group_info['all']
    ]
    
    # Atur 2 tombol per baris
    keyboard = [buttons[i:i+2] for i in range(0, len(buttons), 2)]
    keyboard.append([InlineKeyboardButton("🔙 Kembali", callback_data="back")])
    
    await query.edit_message_text(
        text=f"*{group}* ➜ *{now}*\nPilih node:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def handle_proxy_choice(query, data):
    """Handle pemilihan proxy individual"""
    _, group, proxy = data.split("_", 2)
    await make_api_request('PUT', f'/proxies/{group}', json={"name": proxy})
    await query.edit_message_text(
        text=f"✅ Proxy *{group}* diubah ke ➜ *{proxy}*", 
        parse_mode="Markdown"
    )

async def handle_status_check(query):
    """Handle pengecekan status delay"""
    proxies = (await make_api_request('GET', '/proxies'))['proxies']
    msg = "*⏱ Delay semua grup:*\n\n"
    
    for name, item in proxies.items():
        if item["type"] == "Selector":
            try:
                delay = await make_api_request(
                    'GET',
                    f'/proxies/{name}/delay?url=https://www.google.com&timeout=3000'
                )
                delay_time = delay.get('delay', 'timeout')
                msg += f"• {name}: {delay_time} ms\n"
            except APIError:
                msg += f"• {name}: error\n"
    
    msg += "\n🔙 /start untuk kembali ke menu."
    await query.edit_message_text(msg, parse_mode="Markdown")

async def handle_ip_check(query):
    """Handle pengecekan IP publik"""
    global last_ip_check
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("https://api.myip.com", timeout=5) as resp:
                ip = await resp.json()
                last_ip_check = datetime.now()
                await query.edit_message_text(
                    f"🌐 *IP Publik:* `{ip['ip']}`\n"
                    f"📍 *Negara:* {ip['country']}\n"
                    f"⏱ *Terakhir diperiksa:* {last_ip_check.strftime('%Y-%m-%d %H:%M:%S')}",
                    parse_mode="Markdown"
                )
    except Exception as e:
        logger.error(f"Error checking IP: {e}")
        await query.edit_message_text("❌ Gagal mengambil IP publik.")

async def handle_fastest_proxy(query):
    """Handle pemilihan proxy tercepat"""
    proxies = (await make_api_request('GET', '/proxies'))['proxies']
    result = []
    
    for name in proxies:
        if proxies[name]['type'] == 'Selector':
            group_info = await make_api_request('GET', f'/proxies/{name}')
            delays = []
            
            for node in group_info['all']:
                try:
                    d = await make_api_request(
                        'GET',
                        f'/proxies/{node}/delay?url=https://www.google.com&timeout=2000'
                    )
                    if 'delay' in d:
                        delays.append((node, d['delay']))
                except APIError:
                    continue
            
            if delays:
                fastest = min(delays, key=lambda x: x[1])
                await make_api_request(
                    'PUT',
                    f'/proxies/{name}',
                    json={"name": fastest[0]}
                )
                result.append(f"• {name} ➜ {fastest[0]} ({fastest[1]} ms)")
    
    msg = "*⚡ Proxy Tercepat Dipilih:*\n" + "\n".join(result) if result else "Tidak ada proxy yang tersedia."
    await query.edit_message_text(msg, parse_mode="Markdown")

async def handle_reload_config(query):
    """Handle reload konfigurasi"""
    await make_api_request('PUT', '/configs?force=true', json={"path": "", "payload": ""})
    await query.edit_message_text("✅ Config berhasil di-reload.")

async def handle_restart(query):
    """Handle restart service"""
    await make_api_request('POST', '/restart')
    await query.edit_message_text("🔄 Mihomo sedang restart...")

async def handle_version_check(query):
    """Handle pengecekan versi"""
    version = await make_api_request('GET', '/version')
    await query.edit_message_text(f"ℹ️ *Versi Clash:* `{version['version']}`", parse_mode="Markdown")

async def handle_backup(query):
    """Handle backup konfigurasi"""
    try:
        async with aiohttp.ClientSession(headers=HEADERS) as session:
            async with session.get(f"{MIHOMO_API}/configs") as response:
                if response.status != 200:
                    raise APIError("Gagal mengambil config")
                
                config_data = await response.text()
                filename = f"config_{datetime.now().strftime('%Y%m%d_%H%M%S')}.yaml"
                
                with open(filename, "w", encoding="utf-8") as f:
                    f.write(config_data)
                
                with open(filename, "rb") as f:
                    await query.message.reply_document(
                        document=InputFile(f, filename=filename),
                        caption="📂 Backup config"
                    )
                
                os.remove(filename)
                await query.delete_message()
    except Exception as e:
        logger.error(f"Error during backup: {e}")
        await query.edit_message_text("❌ Gagal membuat backup config.")

async def handle_back_to_menu(query):
    """Kembali ke menu utama"""
    proxies = (await make_api_request('GET', '/proxies'))['proxies']
    await query.edit_message_text(
        "📋 Menu Utama:",
        reply_markup=main_menu_keyboard(proxies)
    )

async def ip_monitor(app):
    """Monitor perubahan IP publik"""
    global current_ip, last_ip_check
    
    while True:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get("https://api.myip.com", timeout=5) as resp:
                    data = await resp.json()
                    if current_ip != data["ip"]:
                        current_ip = data["ip"]
                        last_ip_check = datetime.now()
                        
                        for admin_id in ADMIN_IDS:
                            try:
                                await app.bot.send_message(
                                    chat_id=admin_id,
                                    text=f"🔔 *IP Publik berubah:*\n"
                                         f"`{current_ip}`\n"
                                         f"📍 *Negara:* {data['country']}\n"
                                         f"⏱ *Waktu:* {last_ip_check.strftime('%Y-%m-%d %H:%M:%S')}",
                                    parse_mode="Markdown"
                                )
                            except Exception as e:
                                logger.error(f"Gagal mengirim notifikasi IP ke admin {admin_id}: {e}")
        except Exception as e:
            logger.error(f"Error monitoring IP: {e}")
        
        await asyncio.sleep(IP_CHECK_INTERVAL)

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk error yang tidak tertangkap"""
    logger.error(f"Update {update} caused error: {context.error}")
    
    if update.effective_message:
        await update.effective_message.reply_text(
            "❌ Terjadi kesalahan. Silakan coba lagi nanti."
        )

if __name__ == '__main__':
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    # Register handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("yacd", start))  # Alias untuk /start
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_error_handler(error_handler)
    
    # Notifikasi saat bot aktif
    app.post_init(notify_admins)
    
    logger.info("Bot starting...")
    app.run_polling()