import os
import re
import random
import logging
import asyncio
import requests
from bs4 import BeautifulSoup
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

proxy_list = []      # sirf LIVE verified proxies store hoti hain
cancel_flags = {}


# ══════════════════════════════════════════════
#  PROXY HELPERS
# ══════════════════════════════════════════════

def check_proxy_live(proxy: str, timeout: int = 8) -> bool:
    """True return karta hai agar proxy live hai."""
    proxies = {"http": f"http://{proxy}", "https": f"http://{proxy}"}
    try:
        r = requests.get("https://httpbin.org/ip", proxies=proxies, timeout=timeout)
        return r.status_code == 200
    except Exception:
        return False


def get_proxy():
    return random.choice(proxy_list) if proxy_list else None


# ══════════════════════════════════════════════
#  SCRAPER
# ══════════════════════════════════════════════

def scrape_rc(vehicle_number: str):
    url = f"https://vahanx.in/rc-search/{vehicle_number.upper()}"
    proxy = get_proxy()
    proxies = {"http": f"http://{proxy}", "https": f"http://{proxy}"} if proxy else None

    soup = None

    if proxy:
        try:
            resp = requests.get(url, headers=HEADERS, proxies=proxies, timeout=15)
            resp.raise_for_status()
            s = BeautifulSoup(resp.text, "html.parser")
            if s.select_one(".hrcd-cardbody") or s.select_one(".hrc-details-card"):
                soup = s
            else:
                raise ValueError("Proxy response mein data block nahi mila")
        except Exception as e:
            logger.warning("Proxy %s fail: %s — direct try kar raha", proxy, e)

    if soup is None:
        try:
            resp = requests.get(url, headers=HEADERS, proxies=None, timeout=15)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
        except Exception as e2:
            logger.error("Direct bhi fail: %s", e2)
            return None

    data = {}

    for card in soup.select(".hrcd-cardbody"):
        p_tag = card.find("p")
        span_tag = card.find("span")
        if p_tag and span_tag:
            data[span_tag.get_text(strip=True)] = p_tag.get_text(strip=True)

    for col in soup.select(".hrc-details-card .col-sm-6, .hrc-details-card .col-12"):
        span_tag = col.find("span", class_="text-muted")
        p_tag = col.find("p", class_="fw-semibold")
        if span_tag and p_tag:
            data[span_tag.get_text(strip=True)] = p_tag.get_text(strip=True)

    h1 = soup.select_one(".col-12 h1")
    if h1:
        data["Vehicle Number"] = h1.get_text(strip=True)

    return data if data else None


# ══════════════════════════════════════════════
#  FORMATTERS
# ══════════════════════════════════════════════

def format_response(data: dict, vehicle_number: str) -> str:
    lines = [
        f"🚗 *RC Details — {vehicle_number.upper()}*",
        "━━━━━━━━━━━━━━━━━━━━",
    ]
    field_map = [
        ("Vehicle Number",  "🔢 Reg Number"),
        ("Modal Name",      "🚙 Model"),
        ("Owner Name",      "👤 Owner"),
        ("Father's Name",   "👨 Father's Name"),
        ("Owner Serial No", "🔄 Ownership"),
        ("Registered RTO",  "🏛 RTO"),
        ("Code",            "📍 RTO Code"),
        ("City Name",       "🏙 City"),
        ("Address",         "🗺 Address"),
        ("Phone",           "📞 Phone"),
    ]
    found_any = False
    for key, label in field_map:
        val = data.get(key)
        if val:
            lines.append(f"{label}: `{val}`")
            found_any = True

    if not found_any:
        return "❌ Koi details nahi mili. Vehicle number check karo."

    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append("_RC Lookup Bot_")
    return "\n".join(lines)


def is_valid_vehicle(text: str) -> bool:
    pattern = r"^[A-Z]{2}[0-9]{1,2}[A-Z]{1,3}[0-9]{1,4}$"
    return bool(re.match(pattern, text.upper().replace(" ", "")))


def progress_bar(done, total) -> str:
    pct = int((done / total) * 100)
    filled = int(pct / 10)
    bar = "█" * filled + "░" * (10 - filled)
    return f"[{bar}] {pct}%"


# ══════════════════════════════════════════════
#  HANDLERS
# ══════════════════════════════════════════════

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "🚘 *RC Lookup Bot*\n\n"
        "Single lookup:\n"
        "`/rc BR05H4963`\n\n"
        "Bulk lookup:\n"
        "`.txt` file upload karo — ek line mein ek vehicle number\n"
        "Output format: `Vehicle:Mobile:OwnerName`\n\n"
        "⚙️ *Proxy Commands:*\n"
        "`/addproxy ip:port` — live check karke add karta hai\n"
        "`/removeproxy ip:port`\n"
        "`/proxylist`\n"
        "`/testproxy` — sirf status dikhata hai, remove nahi karta\n"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


async def rc_lookup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "⚠️ Vehicle number daao.\nExample: `/rc BR05H4963`",
            parse_mode="Markdown",
        )
        return

    vehicle = context.args[0].strip().replace(" ", "").upper()

    if not is_valid_vehicle(vehicle):
        await update.message.reply_text(
            "⚠️ Valid Indian vehicle number daao.\nExample: `/rc BR05H4963`",
            parse_mode="Markdown",
        )
        return

    proxy_status = f"Proxy ON ({len(proxy_list)})" if proxy_list else "Direct"
    wait_msg = await update.message.reply_text(
        f"🔍 Searching `{vehicle}`... ⏳\n_{proxy_status}_",
        parse_mode="Markdown",
    )

    data = scrape_rc(vehicle)
    await wait_msg.delete()

    if not data:
        await update.message.reply_text("❌ Details fetch nahi ho saki. Vehicle number sahi hai?")
        return

    await update.message.reply_text(format_response(data, vehicle), parse_mode="Markdown")


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if not doc.file_name.endswith(".txt"):
        await update.message.reply_text("⚠️ Sirf `.txt` file upload karo.", parse_mode="Markdown")
        return

    file = await doc.get_file()
    content = await file.download_as_bytearray()
    text = content.decode("utf-8", errors="ignore")

    vehicles = []
    for line in text.splitlines():
        v = line.strip().replace(" ", "").upper()
        if v and is_valid_vehicle(v):
            vehicles.append(v)

    if not vehicles:
        await update.message.reply_text("❌ Koi valid vehicle number nahi mila file mein.")
        return

    user_id = update.effective_user.id
    cancel_flags[user_id] = False

    cancel_btn = InlineKeyboardMarkup([
        [InlineKeyboardButton("🛑 Cancel", callback_data=f"cancel_{user_id}")]
    ])

    progress_msg = await update.message.reply_text(
        f"🚀 Processing *{len(vehicles)}* vehicles...\n{progress_bar(0, len(vehicles))}",
        parse_mode="Markdown",
        reply_markup=cancel_btn,
    )

    results = []   # format: "Vehicle:Mobile:OwnerName"
    skipped = 0
    last_milestone = 0

    for i, vehicle in enumerate(vehicles, 1):
        if cancel_flags.get(user_id):
            break

        data = scrape_rc(vehicle)

        if data:
            phone = data.get("Phone", "").strip()
            owner = data.get("Owner Name", "").strip()
            # Output format: Vehicle:Mobile:OwnerName
            results.append(f"{vehicle}:{phone}:{owner}")
        else:
            skipped += 1

        pct = int((i / len(vehicles)) * 100)
        milestone = (pct // 25) * 25
        if milestone > last_milestone or i == len(vehicles):
            last_milestone = milestone
            try:
                await progress_msg.edit_text(
                    f"🔄 Processing *{len(vehicles)}* vehicles...\n"
                    f"{progress_bar(i, len(vehicles))}\n"
                    f"✅ Found: *{len(results)}* | ⏭ Skipped: *{skipped}*",
                    parse_mode="Markdown",
                    reply_markup=cancel_btn,
                )
            except Exception:
                pass

        await asyncio.sleep(0.5)

    cancelled = cancel_flags.get(user_id, False)
    cancel_flags.pop(user_id, None)

    if not results:
        await progress_msg.edit_text(
            f"{'🛑 Cancelled!' if cancelled else '❌ Koi result nahi mila.'}\n"
            f"Processed: {i} | Skipped: {skipped}",
        )
        return

    output_path = f"/tmp/rc_results_{user_id}.txt"
    with open(output_path, "w") as f:
        f.write("\n".join(results))

    status = "🛑 Cancelled — Partial result:" if cancelled else "✅ Done!"
    await progress_msg.edit_text(
        f"{status}\n"
        f"Total: {len(vehicles)} | Found: {len(results)} | Skipped: {skipped}",
        parse_mode="Markdown",
    )

    with open(output_path, "rb") as f:
        await update.message.reply_document(
            document=f,
            filename="rc_results.txt",
            caption=(
                f"📄 *RC Results*\n"
                f"Format: `Vehicle:Mobile:OwnerName`\n"
                f"✅ Found: {len(results)} | ⏭ Skipped: {skipped}"
            ),
            parse_mode="Markdown",
        )


async def cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("🛑 Cancelling...")
    try:
        user_id = int(query.data.split("_")[1])
        cancel_flags[user_id] = True
    except Exception:
        pass


# ══════════════════════════════════════════════
#  PROXY COMMANDS
# ══════════════════════════════════════════════

async def add_proxy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Proxy add karne se pehle live check karta hai.
    Live hai → add karta hai.
    Dead hai → reject karta hai.
    """
    if not context.args:
        await update.message.reply_text("Format: `/addproxy ip:port`", parse_mode="Markdown")
        return

    proxy = context.args[0].strip()

    if proxy in proxy_list:
        await update.message.reply_text(
            f"⚠️ Proxy already list mein hai: `{proxy}`", parse_mode="Markdown"
        )
        return

    checking_msg = await update.message.reply_text(
        f"🔍 Checking proxy `{proxy}`...", parse_mode="Markdown"
    )

    # Blocking call — run in executor so bot doesn't freeze
    loop = asyncio.get_event_loop()
    is_live = await loop.run_in_executor(None, check_proxy_live, proxy)

    await checking_msg.delete()

    if is_live:
        proxy_list.append(proxy)
        await update.message.reply_text(
            f"✅ Proxy live hai, add ho gaya: `{proxy}`\nTotal: *{len(proxy_list)}*",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text(
            f"💀 Proxy dead hai, add nahi kiya: `{proxy}`",
            parse_mode="Markdown",
        )


async def remove_proxy_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Format: `/removeproxy ip:port`", parse_mode="Markdown")
        return

    proxy = context.args[0].strip()
    if proxy not in proxy_list:
        await update.message.reply_text(
            f"❌ Proxy list mein nahi hai: `{proxy}`", parse_mode="Markdown"
        )
        return

    proxy_list.remove(proxy)
    await update.message.reply_text(
        f"🗑 Proxy remove ho gaya: `{proxy}`\nTotal: *{len(proxy_list)}*",
        parse_mode="Markdown",
    )


async def proxy_list_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not proxy_list:
        await update.message.reply_text(
            "📋 Koi proxy nahi hai.\n`/addproxy ip:port` se add karo.",
            parse_mode="Markdown",
        )
        return

    lines = ["📋 *Active Proxies:*\n"]
    for i, p in enumerate(proxy_list, 1):
        lines.append(f"{i}. `{p}`")
    lines.append(f"\nTotal: *{len(proxy_list)}*")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def test_proxy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Sirf status dikhata hai — koi proxy automatically remove NAHI karta.
    User khud /removeproxy se remove kare agar chahiye.
    """
    if not proxy_list:
        await update.message.reply_text(
            "❌ Koi proxy nahi hai. `/addproxy ip:port` se add karo.",
            parse_mode="Markdown",
        )
        return

    wait_msg = await update.message.reply_text(
        f"🔍 Testing *{len(proxy_list)}* proxies... ⏳", parse_mode="Markdown"
    )

    results = []
    live_count = 0
    dead_count = 0

    loop = asyncio.get_event_loop()

    for proxy in proxy_list:
        is_live = await loop.run_in_executor(None, check_proxy_live, proxy)
        if is_live:
            results.append(f"✅ `{proxy}` — Live")
            live_count += 1
        else:
            results.append(f"💀 `{proxy}` — Dead")
            dead_count += 1

    lines = ["🧪 *Proxy Test Results:*\n"] + results
    lines.append(f"\n✅ Live: *{live_count}* | 💀 Dead: *{dead_count}*")
    lines.append("_(Dead proxies remove karne ke liye `/removeproxy ip:port` use karo)_")

    await wait_msg.delete()
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ══════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════

def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN environment variable set nahi hai!")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("rc", rc_lookup))
    app.add_handler(CommandHandler("addproxy", add_proxy))
    app.add_handler(CommandHandler("removeproxy", remove_proxy_cmd))
    app.add_handler(CommandHandler("proxylist", proxy_list_cmd))
    app.add_handler(CommandHandler("testproxy", test_proxy))
    app.add_handler(MessageHandler(filters.Document.TXT, handle_document))
    app.add_handler(CallbackQueryHandler(cancel_callback, pattern=r"^cancel_"))

    logger.info("RC Lookup Bot starting...")
    app.run_polling()


if __name__ == "__main__":
    main()


def get_proxy():
    if not proxy_list:
        return None
    return random.choice(proxy_list)


def scrape_rc(vehicle_number):
    url = f"https://vahanx.in/rc-search/{vehicle_number.upper()}"
    proxy = get_proxy()
    proxies = {"http": f"http://{proxy}", "https": f"http://{proxy}"} if proxy else None

    try:
        resp = requests.get(url, headers=HEADERS, proxies=proxies, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        if not soup.select_one(".hrcd-cardbody") and not soup.select_one(".hrc-details-card"):
            raise ValueError("No data in proxy response")
    except Exception as e:
        logger.warning("Proxy failed (%s): %s — trying direct", proxy, e)
        if proxy and proxy in proxy_list:
            proxy_list.remove(proxy)
        try:
            resp = requests.get(url, headers=HEADERS, proxies=None, timeout=15)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
        except Exception as e2:
            logger.error("Direct also failed: %s", e2)
            return None

    data = {}

    for card in soup.select(".hrcd-cardbody"):
        p_tag = card.find("p")
        span_tag = card.find("span")
        if p_tag and span_tag:
            data[span_tag.get_text(strip=True)] = p_tag.get_text(strip=True)

    for col in soup.select(".hrc-details-card .col-sm-6, .hrc-details-card .col-12"):
        span_tag = col.find("span", class_="text-muted")
        p_tag = col.find("p", class_="fw-semibold")
        if span_tag and p_tag:
            data[span_tag.get_text(strip=True)] = p_tag.get_text(strip=True)

    h1 = soup.select_one(".col-12 h1")
    if h1:
        data["Vehicle Number"] = h1.get_text(strip=True)

    return data if data else None


def format_response(data, vehicle_number):
    lines = [
        f"🚗 *RC Details — {vehicle_number.upper()}*",
        "━━━━━━━━━━━━━━━━━━━━",
    ]
    field_map = [
        ("Vehicle Number",  "🔢 Reg Number"),
        ("Modal Name",      "🚙 Model"),
        ("Owner Name",      "👤 Owner"),
        ("Father's Name",   "👨 Father's Name"),
        ("Owner Serial No", "🔄 Ownership"),
        ("Registered RTO",  "🏛 RTO"),
        ("Code",            "📍 RTO Code"),
        ("City Name",       "🏙 City"),
        ("Address",         "🗺 Address"),
        ("Phone",           "📞 Phone"),
    ]
    found_any = False
    for key, label in field_map:
        val = data.get(key)
        if val:
            lines.append(f"{label}: `{val}`")
            found_any = True

    if not found_any:
        return "❌ Koi details nahi mili. Vehicle number check karo."

    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append("_RC Lookup Bot_")
    return "\n".join(lines)


def is_valid_vehicle(text):
    pattern = r"^[A-Z]{2}[0-9]{1,2}[A-Z]{1,3}[0-9]{1,4}$"
    return bool(re.match(pattern, text.upper().replace(" ", "")))


def progress_bar(done, total):
    pct = int((done / total) * 100)
    filled = int(pct / 10)
    bar = "█" * filled + "░" * (10 - filled)
    return f"[{bar}] {pct}%"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "🚘 *RC Lookup Bot*\n\n"
        "Single lookup:\n"
        "`/rc BR05H4963`\n\n"
        "Bulk lookup:\n"
        "`.txt` file upload karo — ek line me ek vehicle number\n\n"
        "⚙️ *Proxy Commands:*\n"
        "`/addproxy ip:port`\n"
        "`/removeproxy ip:port`\n"
        "`/proxylist`\n"
        "`/testproxy`\n"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


async def rc_lookup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "⚠️ Vehicle number daao.\nExample: `/rc BR05H4963`",
            parse_mode="Markdown",
        )
        return

    vehicle = context.args[0].strip().replace(" ", "").upper()

    if not is_valid_vehicle(vehicle):
        await update.message.reply_text(
            "⚠️ Valid Indian vehicle number daao.\nExample: `/rc BR05H4963`",
            parse_mode="Markdown",
        )
        return

    proxy_status = f"Proxy ON ({len(proxy_list)})" if proxy_list else "Direct"
    wait_msg = await update.message.reply_text(
        f"🔍 Searching `{vehicle}`... ⏳\n_{proxy_status}_",
        parse_mode="Markdown",
    )

    data = scrape_rc(vehicle)
    await wait_msg.delete()

    if not data:
        await update.message.reply_text("❌ Details fetch nahi ho saki. Vehicle number sahi hai?")
        return

    await update.message.reply_text(format_response(data, vehicle), parse_mode="Markdown")


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if not doc.file_name.endswith(".txt"):
        await update.message.reply_text("⚠️ Sirf `.txt` file upload karo.", parse_mode="Markdown")
        return

    file = await doc.get_file()
    content = await file.download_as_bytearray()
    text = content.decode("utf-8", errors="ignore")

    vehicles = []
    for line in text.splitlines():
        v = line.strip().replace(" ", "").upper()
        if is_valid_vehicle(v):
            vehicles.append(v)

    if not vehicles:
        await update.message.reply_text("❌ Koi valid vehicle number nahi mila file me.")
        return

    user_id = update.effective_user.id
    cancel_flags[user_id] = False

    cancel_btn = InlineKeyboardMarkup([
        [InlineKeyboardButton("🛑 Cancel", callback_data=f"cancel_{user_id}")]
    ])

    progress_msg = await update.message.reply_text(
        f"🚀 Processing *{len(vehicles)}* vehicles...\n{progress_bar(0, len(vehicles))}",
        parse_mode="Markdown",
        reply_markup=cancel_btn,
    )

    results = []
    skipped = 0
    last_milestone = 0

    for i, vehicle in enumerate(vehicles, 1):
        if cancel_flags.get(user_id):
            break

        data = scrape_rc(vehicle)

        if data:
            phone = data.get("Phone", "").strip()
            owner = data.get("Owner Name", "").strip()
            if phone or owner:
                results.append(f"{vehicle}:{phone}:{owner}")
            else:
                skipped += 1
        else:
            skipped += 1

        pct = int((i / len(vehicles)) * 100)
        milestone = (pct // 25) * 25
        if milestone > last_milestone or i == len(vehicles):
            last_milestone = milestone
            try:
                await progress_msg.edit_text(
                    f"🔄 Processing *{len(vehicles)}* vehicles...\n"
                    f"{progress_bar(i, len(vehicles))}\n"
                    f"✅ Found: *{len(results)}* | ⏭ Skipped: *{skipped}*",
                    parse_mode="Markdown",
                    reply_markup=cancel_btn,
                )
            except Exception:
                pass

        await asyncio.sleep(0.5)

    cancelled = cancel_flags.get(user_id, False)
    cancel_flags.pop(user_id, None)

    if not results:
        await progress_msg.edit_text(
            f"{'🛑 Cancelled!' if cancelled else '❌ Koi result nahi mila.'}\n"
            f"Processed: {len(results) + skipped} | Skipped: {skipped}",
        )
        return

    output_path = f"/tmp/rc_results_{user_id}.txt"
    with open(output_path, "w") as f:
        f.write("\n".join(results))

    status = "🛑 Cancelled — Partial result:" if cancelled else "✅ Done!"
    await progress_msg.edit_text(
        f"{status}\n"
        f"Total: {len(vehicles)} | Found: {len(results)} | Skipped: {skipped}",
        parse_mode="Markdown",
    )

    with open(output_path, "rb") as f:
        await update.message.reply_document(
            document=f,
            filename="rc_results.txt",
            caption=f"📄 RC Results\n✅ Found: {len(results)} | ⏭ Skipped: {skipped}",
        )


async def cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("🛑 Cancelling...")
    try:
        user_id = int(query.data.split("_")[1])
        cancel_flags[user_id] = True
    except Exception:
        pass


async def add_proxy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Format: `/addproxy ip:port`", parse_mode="Markdown")
        return
    proxy = context.args[0].strip()
    if proxy in proxy_list:
        await update.message.reply_text(f"⚠️ Proxy already hai: `{proxy}`", parse_mode="Markdown")
        return
    proxy_list.append(proxy)
    await update.message.reply_text(
        f"✅ Proxy add ho gaya: `{proxy}`\nTotal: *{len(proxy_list)}*",
        parse_mode="Markdown",
    )


async def remove_proxy_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Format: `/removeproxy ip:port`", parse_mode="Markdown")
        return
    proxy = context.args[0].strip()
    if proxy not in proxy_list:
        await update.message.reply_text(f"❌ Proxy nahi mila: `{proxy}`", parse_mode="Markdown")
        return
    proxy_list.remove(proxy)
    await update.message.reply_text(
        f"🗑 Proxy remove ho gaya: `{proxy}`\nTotal: *{len(proxy_list)}*",
        parse_mode="Markdown",
    )


async def proxy_list_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not proxy_list:
        await update.message.reply_text(
            "📋 Koi proxy nahi hai.\n`/addproxy ip:port` se add karo.",
            parse_mode="Markdown",
        )
        return
    lines = ["📋 *Active Proxies:*\n"]
    for i, p in enumerate(proxy_list, 1):
        lines.append(f"{i}. `{p}`")
    lines.append(f"\nTotal: *{len(proxy_list)}*")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def test_proxy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not proxy_list:
        await update.message.reply_text(
            "❌ Koi proxy nahi hai. `/addproxy ip:port` se add karo.",
            parse_mode="Markdown",
        )
        return

    wait_msg = await update.message.reply_text("🔍 Testing proxies... ⏳")
    results = []
    dead = []

    for proxy in proxy_list.copy():
        proxies = {"http": f"http://{proxy}", "https": f"http://{proxy}"}
        try:
            r = requests.get("https://httpbin.org/ip", proxies=proxies, timeout=8)
            if r.status_code == 200:
                results.append(f"✅ `{proxy}`")
            else:
                results.append(f"❌ `{proxy}` — {r.status_code}")
                dead.append(proxy)
        except Exception:
            results.append(f"💀 `{proxy}` — Dead")
            dead.append(proxy)

    for d in dead:
        if d in proxy_list:
            proxy_list.remove(d)

    lines = ["🧪 *Proxy Test Results:*\n"] + results
    if dead:
        lines.append(f"\n🗑 *{len(dead)} dead proxy remove ho gaye*")
    lines.append(f"\n✅ Active: *{len(proxy_list)}*")

    await wait_msg.delete()
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN environment variable set nahi hai!")
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("rc", rc_lookup))
    app.add_handler(CommandHandler("addproxy", add_proxy))
    app.add_handler(CommandHandler("removeproxy", remove_proxy_cmd))
    app.add_handler(CommandHandler("proxylist", proxy_list_cmd))
    app.add_handler(CommandHandler("testproxy", test_proxy))
    app.add_handler(MessageHandler(filters.Document.TXT, handle_document))
    app.add_handler(CallbackQueryHandler(cancel_callback, pattern=r"^cancel_"))
    logger.info("RC Lookup Bot starting...")
    app.run_polling()


if __name__ == "__main__":
    main()
