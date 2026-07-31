import re
import time
import logging
from collections import defaultdict, deque

from telegram import Update, ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    ContextTypes,
    MessageHandler,
    CommandHandler,
    filters,
)

# @BotFather'dan aldığın YENİ token'ı buraya tırnak içine yapıştır
TOKEN = "8373776162:AAEC9A48pIo1PDQTZ8VB8qMmptpEWVWcyHw"
ADMIN_CHAT_ID = 8531974377

FLOOD_WINDOW_SECONDS = 8
FLOOD_MAX_MESSAGES = 6

CARD_NUMBER_RE = re.compile(r"\b(?:\d[ -]?){13,19}\b")
CVV_RE = re.compile(r"\b(cvv|cvc|güvenlik kodu)\D{0,5}\d{3,4}\b", re.IGNORECASE)
EXPIRY_RE = re.compile(r"\b(0[1-9]|1[0-2])[/\-]\d{2,4}\b")

def luhn_check(number: str) -> bool:
    digits = [int(d) for d in number if d.isdigit()]
    if len(digits) < 13:
        return False
    checksum = 0
    parity = len(digits) % 2
    for i, d in enumerate(digits):
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        checksum += d
    return checksum % 10 == 0


def tc_kimlik_check(number: str) -> bool:
    if len(number) != 11 or not number.isdigit():
        return False
    if number[0] == "0":
        return False
    digits = [int(d) for d in number]
    odd_sum = sum(digits[0:9:2])
    even_sum = sum(digits[1:8:2])
    digit10 = ((odd_sum * 7) - even_sum) % 10
    if digit10 != digits[9]:
        return False
    digit11 = sum(digits[0:10]) % 10
    if digit11 != digits[10]:
        return False
    return True


def find_tc_kimlik_numbers(text: str):
    candidates = re.findall(r"\b\d{11}\b", text)
    return [c for c in candidates if tc_kimlik_check(c)]


def find_credit_cards(text: str):
    found = []
    for match in CARD_NUMBER_RE.finditer(text):
        raw = match.group()
        digits_only = re.sub(r"\D", "", raw)
        if 13 <= len(digits_only) <= 19 and luhn_check(digits_only):
            found.append(raw)
    return found


def contains_cvv_or_expiry(text: str) -> bool:
    return bool(CVV_RE.search(text)) or bool(EXPIRY_RE.search(text) and re.search(r"kart|card", text, re.IGNORECASE))


user_message_times = defaultdict(lambda: deque())


def is_flooding(chat_id: int, user_id: int) -> bool:
    key = (chat_id, user_id)
    now = time.time()
    dq = user_message_times[key]
    dq.append(now)
    while dq and now - dq[0] > FLOOD_WINDOW_SECONDS:
        dq.popleft()
    return len(dq) > FLOOD_MAX_MESSAGES


async def punish(update: Update, context: ContextTypes.DEFAULT_TYPE, reason: str, action: str = "mute"):
    chat_id = update.effective_chat.id
    user = update.effective_user
    message = update.effective_message

    try:
        await message.delete()
    except Exception as e:
        logging.warning(f"Mesaj silinemedi: {e}")

    if action == "mute":
        try:
            await context.bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user.id,
                permissions=ChatPermissions(can_send_messages=False)
            )
            action_text = "🔇 Susturuldu (Mute)"
        except Exception as e:
            logging.warning(f"Kullanıcı susturulamadı: {e}")
            action_text = "Cezalandırılamadı"
    else:
        try:
            await context.bot.ban_chat_member(chat_id=chat_id, user_id=user.id)
            action_text = "🚫 Banlandı"
        except Exception as e:
            logging.warning(f"Kullanıcı banlanamadı: {e}")
            action_text = "Cezalandırılamadı"

    if ADMIN_CHAT_ID:
        try:
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=(
                    f"🚨 <b>Otomatik İşlem ({action_text})</b>\n"
                    f"Kullanıcı: {user.mention_html()} (ID: <code>{user.id}</code>)\n"
                    f"Grup: {update.effective_chat.title or chat_id}\n"
                    f"Sebep: {reason}"
                ),
                parse_mode=ParseMode.HTML,
            )
        except Exception as e:
            logging.warning(f"Admin bildirimi gönderilemedi: {e}")


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_info = await context.bot.get_me()
    add_to_group_url = f"https://t.me/{bot_info.username}?startgroup=true"

    keyboard = [
        [InlineKeyboardButton("➕ Beni Gruba Ekle", url=add_to_group_url)],
        [InlineKeyboardButton("💬 İletişim / Kurucu", url="https://t.me/userullah")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    welcome_text = (
        "👑 <b>Honośizm'e hoş geldiniz</b> 👑\n\n"
        "🛡️ <b>Super Guard & Moderasyon Botu</b>\n\n"
        "Grubunuzu 7/24 kesintisiz korumak için buradayım!\n\n"
        "⚡ <b>Gelişmiş Özellikler:</b>\n"
        "• 🛑 <b>Spam & Flood Koruması:</b> Üst üste hızlı mesaj atanları anında <b>Mute (Susturma)</b> atar.\n"
        "• 💳 <b>Kredi Kartı Koruması:</b> Kart numarası ve CVV paylaşımlarını anında siler.\n"
        "• 🆔 <b>TC Kimlik Koruması:</b> Kişisel veri ihlallerini tespit edip engeller.\n"
        "• 🚨 <b>Admin Bildirimi:</b> İhlal yapanları detaylı şekilde yöneticiye bildirir.\n\n"
        "📌 <i>Beni grubunuza ekleyip <b>Yönetici (Admin)</b> yetkisi vermeniz yeterlidir.</i>\n\n"
        "💬 <b>İletişim:</b> @userullah"
    )

    await update.effective_message.reply_text(
        welcome_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    if message is None:
        return

    chat_id = update.effective_chat.id
    user = update.effective_user

    text = message.text or message.caption or ""
    if text:
        cards = find_credit_cards(text)
        if cards:
            await punish(update, context, "Kredi kartı numarası paylaşımı", action="ban")
            return

        if contains_cvv_or_expiry(text):
            await punish(update, context, "CVV / kart son kullanma tarihi paylaşımı", action="ban")
            return

        tc_numbers = find_tc_kimlik_numbers(text)
        if tc_numbers:
            await punish(update, context, "TC Kimlik No paylaşımı (kişisel veri)", action="ban")
            return

    if is_flooding(chat_id, user.id):
        await punish(update, context, f"Spam & Flood ({FLOOD_MAX_MESSAGES}+ mesaj / {FLOOD_WINDOW_SECONDS}sn)", action="mute")
        return


def main():
    logging.basicConfig(level=logging.INFO)

    if TOKEN == "BURAYA_YENI_TOKENINIZI_YAZIN":
        raise SystemExit("Lütfen TOKEN değişkenine gerçek bot token'ını gir.")

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, on_message))

    print("Bot çalışıyor...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
  
