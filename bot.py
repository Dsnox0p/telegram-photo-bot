
import os
import json
import asyncio
import logging
from pathlib import Path

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)

# ===== SETTINGS: environment variables mein set karo =====
TOKEN = os.environ["BOT_TOKEN"]
ADMIN_PASSWORD = os.environ["ADMIN_PASSWORD"]

DATA_FILE = Path(os.getenv("DATA_FILE", "bot_data.json"))
MAX_CARDS = 4

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# ===== JSON STORAGE =====
def load_data():
    if DATA_FILE.exists():
        try:
            data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
            data.setdefault("cards", [])
            data.setdefault("admins", [])
            return data
        except (json.JSONDecodeError, OSError):
            log.exception("Data file read nahi hui")
    return {"cards": [], "admins": []}

data = load_data()
save_lock = asyncio.Lock()


async def save_data():
    async with save_lock:
        DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        temp = DATA_FILE.with_suffix(".tmp")
        temp.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        temp.replace(DATA_FILE)


def is_admin(user_id):
    return user_id in data["admins"]


def valid_url(url):
    return url.startswith(("https://", "http://"))


def card_keyboard(card):
    rows = [[
        InlineKeyboardButton("📢 Channel", url=card["channel"]),
        InlineKeyboardButton("👥 Group", url=card["group"])
    ]]
    if card.get("html"):
        rows.append([
            InlineKeyboardButton("🌐 Open Website", url=card["html"])
        ])
    return InlineKeyboardMarkup(rows)


async def show_cards(message):
    if not data["cards"]:
        await message.reply_text(
            "Abhi koi photo card nahi hai. Admin se setup karwao."
        )
        return

    for card in data["cards"]:
        try:
            await message.reply_photo(
                photo=card["photo"],
                caption=card.get("caption", ""),
                reply_markup=card_keyboard(card)
            )
        except Exception:
            log.exception("Card send nahi hua: %s", card.get("id"))


# ===== USER START =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_cards(update.effective_message)


# ===== ADMIN LOGIN =====
async def admin_login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["mode"] = "password"
    await update.effective_message.reply_text(
        "🔐 Admin password bhejo.\nCancel karne ke liye /cancel"
    )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("mode", None)
    context.user_data.pop("new_card", None)
    context.user_data.pop("edit_id", None)
    await update.effective_message.reply_text("Cancelled.")
    

async def panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.effective_message.reply_text(
            "Access nahi hai. Login ke liye /admin use karo."
        )
        return
    await show_panel(update.effective_message)


async def show_panel(message):
    keyboard = [
        [InlineKeyboardButton("➕ Add Card", callback_data="add")],
        [InlineKeyboardButton("🖼 Manage Cards", callback_data="list")],
    ]
    await message.reply_text(
        "⚙️ ADMIN PANEL\n\nCards add, edit ya delete karo.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ===== ADMIN BUTTONS =====
async def callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if not is_admin(q.from_user.id):
        await q.message.reply_text("Access denied.")
        return

    action = q.data

    if action == "add":
        if len(data["cards"]) >= MAX_CARDS:
            await q.message.reply_text(
                f"Maximum {MAX_CARDS} cards allowed. Pehle ek delete karo."
            )
            return
        context.user_data["mode"] = "new_photo"
        context.user_data["new_card"] = {}
        await q.message.reply_text("Nayi card ki photo bhejo.")

    elif action == "list":
        if not data["cards"]:
            await q.message.reply_text("Koi card nahi hai.")
            return
        rows = []
        for c in data["cards"]:
            rows.append([InlineKeyboardButton(
                f"Card {c['id']}: {c.get('caption', 'No title')[:25]}",
                callback_data=f"card:{c['id']}"
            )])
        rows.append([InlineKeyboardButton("⬅️ Panel", callback_data="home")])
        await q.message.reply_text(
            "Edit/delete ke liye card chuno:",
            reply_markup=InlineKeyboardMarkup(rows)
        )

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
            [InlineKeyboardButton("📢 Change Channel Link", callback_data="edit:channel")],
            [InlineKeyboardButton("👥 Change Group Link", callback_data="edit:group")],
            [InlineKeyboardButton("🌐 Change HTML Link", callback_data="edit:html")],
            [InlineKeyboardButton("🗑 Delete Card", callback_data="delete")],
            [InlineKeyboardButton("⬅️ Back", callback_data="list")]
        ]
        await q.message.reply_text(
            f"Card {cid} — {card.get('caption', '')}",
            reply_markup=InlineKeyboardMarkup(rows)
        )

    elif action.startswith("edit:"):
        field = action.split(":")[1]
        context.user_data["mode"] = "edit_" + field
        prompts = {
            "photo": "Nayi photo bhejo.",
            "caption": "Naya caption bhejo.",
            "channel": "Naya Channel URL bhejo (https://...).",
            "group": "Naya Group URL bhejo (https://...).",
            "html": "Naya HTML/website URL bhejo. Button hatane ke liye NONE bhejo."
        }
        await q.message.reply_text(prompts[field])

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
        # Login password ko log ya reply mein echo nahi karte.
        if not is_admin(uid) and msg.text != ADMIN_PASSWORD:
            await msg.reply_text("❌ Password galat hai. /cancel ya dobara try karo.")
            return

        if not is_admin(uid):
            data["admins"].append(uid)
            await save_data()

        context.user_data.pop("mode", None)
        await msg.reply_text(
            "✅ Admin access mil gaya.\n/panel likhkar controls kholo."
        )
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
            await msg.reply_text("Card ka caption bhejo.")
        else:
            card = find_edit_card(context)
            if card:
                card["photo"] = photo_id
                await save_data()
            context.user_data.pop("mode", None)
            await msg.reply_text("✅ Photo change ho gayi.")
        return

    if mode == "new_caption":
        context.user_data["new_card"]["caption"] = msg.text or ""
        context.user_data["mode"] = "new_channel"
        await msg.reply_text("Channel ka full URL bhejo (https://...).")
        return

    if mode == "new_channel":
        if not msg.text or not valid_url(msg.text.strip()):
            await msg.reply_text("Sahi http/https URL bhejo.")
            return
        context.user_data["new_card"]["channel"] = msg.text.strip()
        context.user_data["mode"] = "new_group"
        await msg.reply_text("Group ka full URL bhejo (https://...).")
        return

    if mode == "new_group":
        if not msg.text or not valid_url(msg.text.strip()):
            await msg.reply_text("Sahi http/https URL bhejo.")
            return
        context.user_data["new_card"]["group"] = msg.text.strip()
        context.user_data["mode"] = "new_html"
        await msg.reply_text("HTML/website URL bhejo, ya NONE agar nahi chahiye.")
        return

    if mode == "new_html":
        url = (msg.text or "").strip()
        if url.upper() != "NONE" and not valid_url(url):
            await msg.reply_text("Sahi URL ya NONE bhejo.")
            return
        if len(data["cards"]) >= MAX_CARDS:
            context.user_data.pop("mode", None)
            context.user_data.pop("new_card", None)
            await msg.reply_text("Card limit poori ho gayi.")
            return
        card = context.user_data["new_card"]
        card["html"] = "" if url.upper() == "NONE" else url
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
        if field in ("channel", "group", "html"):
            if field == "html" and value.upper() == "NONE":
                value = ""
            elif not valid_url(value):
                await msg.reply_text("Sahi http/https URL bhejo.")
                return

        if field == "caption":
            card["caption"] = msg.text or ""
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
    app.add_handler(CallbackQueryHandler(callbacks))
    app.add_handler(MessageHandler(
        filters.PHOTO | (filters.TEXT & ~filters.COMMAND),
        incoming
    ))
    app.add_error_handler(error_handler)

    print("Bot is running...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
