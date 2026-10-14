import os
import json
import asyncio
import logging
from pathlib import Path
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters

# ===== SETTINGS =====
TOKEN = os.environ["BOT_TOKEN"]
ADMIN_PASSWORD = os.environ["ADMIN_PASSWORD"]
REMOVE_ADMIN_SECRET = os.getenv("REMOVE_ADMIN_SECRET", "")
DATA_FILE = Path(os.getenv("DATA_FILE", "bot_data.json"))
MAX_CARDS = 4

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# ===== JSON STORAGE (existing cards/admins are preserved) =====
def load_data():
    if DATA_FILE.exists():
        try:
            loaded = json.loads(DATA_FILE.read_text(encoding="utf-8"))
            loaded.setdefault("cards", [])
            loaded.setdefault("admins", [])
            return loaded
        except (json.JSONDecodeError, OSError):
            log.exception("Data file read nahi hui")
    return {"cards": [], "admins": []}

data = load_data()
save_lock = asyncio.Lock()

async def save_data():
    async with save_lock:
        DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        temp = DATA_FILE.with_suffix(".tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(DATA_FILE)

def is_admin(user_id):
    return user_id in data["admins"]

def valid_url(url):
    return url.startswith(("https://", "http://"))

def card_keyboard(card):
    rows = []
    # Backward compatible: old cards keep showing their Channel button.
    channel_url = card.get("channel", "")
    if channel_url:
        rows.append([InlineKeyboardButton(card.get("channel_title") or "📢 Channel", url=channel_url)])
    buy_url = card.get("html", "")
    if buy_url:
        item = card.get("item_name", "1 BG")
        amount = card.get("amount", "30")
        buy_title = card.get("buy_title") or f"🛒 Buy {item} — ₹{amount}"
        rows.append([InlineKeyboardButton(buy_title, url=buy_url)])
    group_url = card.get("group", "")
    if group_url:
        rows.append([InlineKeyboardButton(card.get("group_title") or "📤 Share Group", url=group_url)])
    return InlineKeyboardMarkup(rows) if rows else None

async def show_cards(message):
    if not data["cards"]:
        await message.reply_text("Abhi koi photo card nahi hai. Admin se setup karwao.")
        return
    for card in data["cards"]:
        try:
            await message.reply_photo(photo=card["photo"], caption=card.get("caption", ""), reply_markup=card_keyboard(card))
        except Exception:
            log.exception("Card send nahi hua: %s", card.get("id"))

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_cards(update.effective_message)

async def admin_login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["mode"] = "password"
    await update.effective_message.reply_text("🔐 Admin password bhejo.\nCancel karne ke liye /cancel")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for key in ("mode", "new_card", "edit_id", "remove_admin_target"):
        context.user_data.pop(key, None)
    await update.effective_message.reply_text("Cancelled.")

async def panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.effective_message.reply_text("Access nahi hai. Login ke liye /admin use karo.")
        return
    await show_panel(update.effective_message)

async def show_panel(message):
    keyboard = [
        [InlineKeyboardButton("➕ Add Card", callback_data="add")],
        [InlineKeyboardButton("🖼 Manage Cards", callback_data="list")],
    ]
    await message.reply_text("⚙️ ADMIN PANEL\n\nCards add, edit ya delete karo.", reply_markup=InlineKeyboardMarkup(keyboard))

async def removeadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.effective_message.reply_text("Access nahi hai.")
        return
    if not REMOVE_ADMIN_SECRET:
        await update.effective_message.reply_text("Railway Variables mein REMOVE_ADMIN_SECRET set karo.")
        return
    context.user_data["mode"] = "remove_admin_secret"
    await update.effective_message.reply_text("Secret code bhejo. Cancel: /cancel")

async def users_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.effective_message.reply_text("Access nahi hai.")
        return
    await update.effective_message.reply_text(f"Total admins: {len(data['admins'])}\n" + "\n".join(str(x) for x in data["admins"]))

async def callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id):
        await q.message.reply_text("Access denied.")
        return
    action = q.data

    if action == "add":
        if len(data["cards"]) >= MAX_CARDS:
            await q.message.reply_text(f"Maximum {MAX_CARDS} cards allowed. Pehle ek delete karo.")
            return
        context.user_data["mode"] = "new_photo"
        context.user_data["new_card"] = {}
        await q.message.reply_text("Nayi card ki photo bhejo.")

    elif action == "list":
        if not data["cards"]:
            await q.message.reply_text("Koi card nahi hai.")
            return
        rows = [[InlineKeyboardButton(f"Card {c['id']}: {c.get('caption', 'No title')[:25]}", callback_data=f"card:{c['id']}")] for c in data["cards"]]
        rows.append([InlineKeyboardButton("⬅️ Panel", callback_data="home")])
        await q.message.reply_text("Edit/delete ke liye card chuno:", reply_markup=InlineKeyboardMarkup(rows))

    elif action == "home":
        await show_panel(q.message)

    elif action.startswith("card:"):
        cid = int(action.split(":")[1])
        card = next((c for c in data["cards"] if c["id"] == cid), None)
        if not card:
            await q.message.reply_text("Card nahi mila.")
            return
        context.user_data["edit_id"] = cid
        rows = [
            [InlineKeyboardButton("🖼 Change Photo", callback_data="edit:photo")],
            [InlineKeyboardButton("✏️ Change Caption", callback_data="edit:caption")],
            [InlineKeyboardButton("📢 Channel Button Title", callback_data="edit:channel_title")],
            [InlineKeyboardButton("🔗 Channel Link", callback_data="edit:channel")],
            [InlineKeyboardButton("🛒 Buy Button Title", callback_data="edit:buy_title")],
            [InlineKeyboardButton("💰 Buy Amount", callback_data="edit:amount")],
            [InlineKeyboardButton("📦 Item Name", callback_data="edit:item_name")],
            [InlineKeyboardButton("🌐 Buy Website Link", callback_data="edit:html")],
            [InlineKeyboardButton("📤 Share Group Button Title", callback_data="edit:group_title")],
            [InlineKeyboardButton("👥 Share Group Link", callback_data="edit:group")],
            [InlineKeyboardButton("🗑 Delete Card", callback_data="delete")],
            [InlineKeyboardButton("⬅️ Back", callback_data="list")],
        ]
        await q.message.reply_text(f"Card {cid} — {card.get('caption', '')}\nKisi field ko skip karne ke liye SKIP bhejo; link/button hatane ke liye NONE bhejo.", reply_markup=InlineKeyboardMarkup(rows))

    elif action.startswith("edit:"):
        field = action.split(":", 1)[1]
        context.user_data["mode"] = "edit_" + field
        prompts = {
            "photo": "Nayi photo bhejo. Photo change nahi karni to /cancel.",
            "caption": "Naya caption bhejo (blank chhodne ke liye SKIP).",
            "channel_title": "Channel button ka naya title bhejo, ya SKIP.",
            "channel": "Naya Channel URL bhejo (https://...), NONE se button hatao, SKIP se purani value rakho.",
            "buy_title": "Buy button ka poora title bhejo, jaise 🛒 Buy 1 BG — ₹30; SKIP se purana title rahega; NONE se default title hoga.",
            "amount": "Naya amount sirf number mein bhejo, jaise 30; SKIP se purana amount rahega.",
            "item_name": "Naya item name bhejo, jaise 1 BG; SKIP se purana rahega.",
            "html": "Buy website URL bhejo (https://...), NONE se Buy button hatao, SKIP se purana link rahega.",
            "group_title": "Share Group button ka title bhejo, ya SKIP.",
            "group": "Group link bhejo (https://...), NONE se button hatao, SKIP se purana link rahega.",
        }
        await q.message.reply_text(prompts[field])

    elif action.startswith("removeadmin:"):
        target = int(action.split(":")[1])
        if target == q.from_user.id:
            await q.message.reply_text("Apne aap ko is command se remove nahi kar sakte.")
            return
        if target not in data["admins"]:
            await q.message.reply_text("Admin pehle hi remove ho chuka hai.")
            return
        data["admins"].remove(target)
        await save_data()
        await q.message.reply_text(f"✅ Admin {target} remove ho gaya.")

    elif action == "delete":
        cid = context.user_data.get("edit_id")
        data["cards"] = [c for c in data["cards"] if c["id"] != cid]
        await save_data()
        context.user_data.pop("edit_id", None)
        await q.message.reply_text("🗑 Card delete ho gaya.")

# ===== RECEIVE PHOTO / TEXT =====
async def incoming(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    uid = update.effective_user.id
    mode = context.user_data.get("mode")
    if not mode:
        return

    if mode == "password":
        if not is_admin(uid) and msg.text != ADMIN_PASSWORD:
            await msg.reply_text("❌ Password galat hai. /cancel ya dobara try karo.")
            return
        if not is_admin(uid):
            data["admins"].append(uid)
            await save_data()
        context.user_data.pop("mode", None)
        await msg.reply_text("✅ Admin access mil gaya.\n/panel likhkar controls kholo.")
        return

    if mode == "remove_admin_secret":
        if msg.text != REMOVE_ADMIN_SECRET:
            await msg.reply_text("❌ Secret code galat hai. Dobara try karo ya /cancel.")
            return
        context.user_data.pop("mode", None)
        targets = [a for a in data["admins"] if a != uid]
        if not targets:
            await msg.reply_text("Remove karne ke liye koi doosra admin nahi hai.")
            return
        keyboard = [[InlineKeyboardButton(f"Remove admin {a}", callback_data=f"removeadmin:{a}")] for a in targets]
        await msg.reply_text("Kis admin ko remove karna hai?", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if not is_admin(uid):
        context.user_data.pop("mode", None)
        await msg.reply_text("Access denied.")
        return

    if mode in ("new_photo", "edit_photo"):
        if not msg.photo:
            await msg.reply_text("Photo image ke roop mein bhejo.")
            return
        photo_id = msg.photo[-1].file_id
        if mode == "new_photo":
            context.user_data["new_card"]["photo"] = photo_id
            context.user_data["mode"] = "new_caption"
            await msg.reply_text("Card ka caption bhejo, ya SKIP.")
        else:
            card = find_edit_card(context)
            if card:
                card["photo"] = photo_id
                await save_data()
            context.user_data.pop("mode", None)
            await msg.reply_text("✅ Photo change ho gayi.")
        return

    if mode == "new_caption":
        caption = (msg.text or "").strip()
        context.user_data["new_card"]["caption"] = "" if caption.upper() == "SKIP" else caption
        context.user_data["mode"] = "new_channel_title"
        await msg.reply_text("Channel button ka title bhejo (default: 📢 Channel), ya SKIP.")
        return

    if mode == "new_channel_title":
        value = (msg.text or "").strip()
        if value.upper() != "SKIP":
            context.user_data["new_card"]["channel_title"] = "" if value.upper() == "NONE" else value
        context.user_data["mode"] = "new_channel"
        await msg.reply_text("Channel URL bhejo (https://...), ya SKIP agar button nahi chahiye.")
        return

    if mode == "new_channel":
        value = (msg.text or "").strip()
        if value.upper() != "SKIP":
            if value.upper() != "NONE" and not valid_url(value):
                await msg.reply_text("Sahi http/https URL, SKIP ya NONE bhejo.")
                return
            context.user_data["new_card"]["channel"] = "" if value.upper() == "NONE" else value
        context.user_data["mode"] = "new_item_name"
        await msg.reply_text("Item name bhejo, jaise 1 BG, ya SKIP.")
        return

    if mode == "new_item_name":
        value = (msg.text or "").strip()
        if value.upper() != "SKIP":
            context.user_data["new_card"]["item_name"] = value
        else:
            context.user_data["new_card"]["item_name"] = "1 BG"
        context.user_data["mode"] = "new_amount"
        await msg.reply_text("Amount bhejo, jaise 30, ya SKIP.")
        return

    if mode == "new_amount":
        value = (msg.text or "").strip()
        if value.upper() == "SKIP":
            context.user_data["new_card"]["amount"] = "30"
        elif value.isdigit():
            context.user_data["new_card"]["amount"] = value
        else:
            await msg.reply_text("Amount number mein bhejo, jaise 30, ya SKIP.")
            return
        context.user_data["mode"] = "new_buy_title"
        await msg.reply_text("Buy button ka title bhejo, ya SKIP for default title.")
        return

    if mode == "new_buy_title":
        value = (msg.text or "").strip()
        if value.upper() != "SKIP":
            context.user_data["new_card"]["buy_title"] = "" if value.upper() == "NONE" else value
        context.user_data["mode"] = "new_html"
        await msg.reply_text("Buy website/payment URL bhejo (https://...), ya SKIP agar button nahi chahiye.")
        return

    if mode == "new_html":
        value = (msg.text or "").strip()
        if value.upper() != "SKIP":
            if value.upper() != "NONE" and not valid_url(value):
                await msg.reply_text("Sahi URL, SKIP ya NONE bhejo.")
                return
            context.user_data["new_card"]["html"] = "" if value.upper() == "NONE" else value
        context.user_data["mode"] = "new_group_title"
        await msg.reply_text("Share Group button ka title bhejo, ya SKIP.")
        return

    if mode == "new_group_title":
        value = (msg.text or "").strip()
        if value.upper() != "SKIP":
            context.user_data["new_card"]["group_title"] = "" if value.upper() == "NONE" else value
        context.user_data["mode"] = "new_group"
        await msg.reply_text("Share Group URL bhejo (https://...), ya SKIP agar button nahi chahiye.")
        return

    if mode == "new_group":
        value = (msg.text or "").strip()
        if value.upper() != "SKIP":
            if value.upper() != "NONE" and not valid_url(value):
                await msg.reply_text("Sahi URL, SKIP ya NONE bhejo.")
                return
            context.user_data["new_card"]["group"] = "" if value.upper() == "NONE" else value
        if len(data["cards"]) >= MAX_CARDS:
            context.user_data.pop("mode", None)
            context.user_data.pop("new_card", None)
            await msg.reply_text("Card limit poori ho gayi.")
            return
        card = context.user_data["new_card"]
        card["id"] = max([c["id"] for c in data["cards"]], default=0) + 1
        data["cards"].append(card)
        await save_data()
        context.user_data.pop("new_card", None)
        context.user_data.pop("mode", None)
        await msg.reply_text("✅ Card save ho gaya! /panel kholo.")
        return

    if mode.startswith("edit_"):
        field = mode[5:]
        card = find_edit_card(context)
        if not card:
            context.user_data.pop("mode", None)
            await msg.reply_text("Card nahi mila.")
            return
        value = (msg.text or "").strip()
        if value.upper() == "SKIP":
            context.user_data.pop("mode", None)
            await msg.reply_text("⏭️ Skip ho gaya; purani value same hai.")
            return
        if field in ("channel", "html", "group"):
            if value.upper() == "NONE":
                value = ""
            elif not valid_url(value):
                await msg.reply_text("Sahi http/https URL, NONE ya SKIP bhejo.")
                return
        elif field == "amount":
            if not value.isdigit():
                await msg.reply_text("Amount number mein bhejo, jaise 30, ya SKIP.")
                return
        if field == "caption":
            card["caption"] = "" if value.upper() == "NONE" else msg.text
        elif field in ("channel_title", "buy_title", "group_title") and value.upper() == "NONE":
            card[field] = ""
        else:
            card[field] = value
        await save_data()
        context.user_data.pop("mode", None)
        await msg.reply_text("✅ Update save ho gaya. /panel kholo.")


def find_edit_card(context):
    cid = context.user_data.get("edit_id")
    return next((c for c in data["cards"] if c["id"] == cid), None)

async def error_handler(update, context):
    log.exception("Bot error", exc_info=context.error)

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_login))
    app.add_handler(CommandHandler("panel", panel))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CommandHandler("removeadmin", removeadmin))
    app.add_handler(CommandHandler("users", users_command))
    app.add_handler(CallbackQueryHandler(callbacks))
    app.add_handler(MessageHandler(filters.PHOTO | (filters.TEXT & ~filters.COMMAND), incoming))
    app.add_error_handler(error_handler)
    print("Bot is running...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
                                      
