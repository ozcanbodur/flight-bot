import os
import logging
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

from flight_checker import search_flights, format_price_message

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

ORIGIN, DESTINATION, DEPART_DATE, RETURN_DATE, PASSENGERS, CONFIRM = range(6)

active_watches = {}


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "✈️ Uçuş Fiyat Takip Botuna hoş geldiniz.\n\n"
        "Seçtiğiniz rota için her saat başı fiyat kontrolü yaparım.\n\n"
        "Komutlar:\n"
        "/watch - Yeni rota takibi başlat\n"
        "/list - Aktif takibi göster\n"
        "/check - Şimdi fiyat kontrol et\n"
        "/stop - Takibi durdur\n"
        "/cancel - Mevcut işlemi iptal et\n\n"
        "Grup içinde de kullanılabilir. Takip hangi sohbette başlatıldıysa mesajlar oraya gider."
    )
    await update.message.reply_text(text)


async def watch_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "🛫 Kalkış havalimanı veya şehir bilgisini girin\n"
        "Örnek: IST, SAW, SJJ, London"
    )
    return ORIGIN


async def get_origin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["origin"] = update.message.text.strip().upper()
    await update.message.reply_text(
        "🛬 Varış havalimanı veya şehir bilgisini girin\n"
        "Örnek: SJJ, LHR, CDG"
    )
    return DESTINATION


async def get_destination(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["destination"] = update.message.text.strip().upper()
    await update.message.reply_text(
        "📅 Gidiş tarihini girin\n"
        "Format: GG.AA.YYYY - Örnek: 01.05.2026"
    )
    return DEPART_DATE


async def get_depart_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        date_str = update.message.text.strip()
        datetime.strptime(date_str, "%d.%m.%Y")
        context.user_data["depart_date"] = date_str

        keyboard = [[
            InlineKeyboardButton("✅ Evet, gidiş-dönüş", callback_data="roundtrip"),
            InlineKeyboardButton("❌ Hayır, tek yön", callback_data="oneway"),
        ]]

        await update.message.reply_text(
            "🔄 Gidiş-dönüş bilet mi arıyorsunuz?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return RETURN_DATE
    except ValueError:
        await update.message.reply_text(
            "❌ Geçersiz tarih formatı. Lütfen GG.AA.YYYY formatında girin."
        )
        return DEPART_DATE


async def get_return_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "oneway":
        context.user_data["return_date"] = None
        context.user_data["awaiting_return"] = False
        await query.edit_message_text("👥 Kaç yolcu? (1-9)")
        return PASSENGERS

    context.user_data["awaiting_return"] = True
    await query.edit_message_text(
        "📅 Dönüş tarihini girin\n"
        "Format: GG.AA.YYYY"
    )
    return RETURN_DATE


async def get_return_date_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("awaiting_return"):
        await update.message.reply_text("Lütfen önce gidiş-dönüş seçimini yapın.")
        return RETURN_DATE

    try:
        date_str = update.message.text.strip()
        datetime.strptime(date_str, "%d.%m.%Y")
        context.user_data["return_date"] = date_str
        context.user_data["awaiting_return"] = False

        await update.message.reply_text("👥 Kaç yolcu? (1-9)")
        return PASSENGERS
    except ValueError:
        await update.message.reply_text("❌ Geçersiz format. GG.AA.YYYY şeklinde girin.")
        return RETURN_DATE


async def get_passengers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        n = int(update.message.text.strip())
        if not 1 <= n <= 9:
            raise ValueError

        context.user_data["passengers"] = n

        cfg = context.user_data
        ret = cfg.get("return_date") or "Yok (tek yön)"

        summary = (
            f"📋 Takip Özeti\n\n"
            f"🛫 Kalkış: {cfg['origin']}\n"
            f"🛬 Varış: {cfg['destination']}\n"
            f"📅 Gidiş: {cfg['depart_date']}\n"
            f"📅 Dönüş: {ret}\n"
            f"👥 Yolcu: {n}\n\n"
            f"Her saat başı fiyat kontrol edilecek. Onaylıyor musunuz?"
        )

        keyboard = [[
            InlineKeyboardButton("✅ Başlat", callback_data="confirm_yes"),
            InlineKeyboardButton("❌ İptal", callback_data="confirm_no"),
        ]]

        await update.message.reply_text(
            summary,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return CONFIRM
    except ValueError:
        await update.message.reply_text("❌ 1-9 arası bir sayı girin.")
        return PASSENGERS


async def confirm_watch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    chat_id = query.message.chat_id

    if query.data == "confirm_yes":
        cfg = {
            "origin": context.user_data["origin"],
            "destination": context.user_data["destination"],
            "depart_date": context.user_data["depart_date"],
            "return_date": context.user_data.get("return_date"),
            "passengers": context.user_data["passengers"],
        }

        active_watches[chat_id] = cfg

        await query.edit_message_text(
            f"✅ Takip başlatıldı.\n\n"
            f"{cfg['origin']} → {cfg['destination']} rotası her saat başı kontrol edilecek.\n"
            f"İlk kontrol şimdi yapılıyor..."
        )

        await do_price_check(context.application, chat_id, cfg)

    else:
        await query.edit_message_text(
            "❌ İptal edildi. /watch ile tekrar başlayabilirsiniz."
        )

    return ConversationHandler.END


async def list_watches(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    if chat_id not in active_watches:
        await update.message.reply_text("📭 Aktif takibiniz bulunmuyor. /watch ile başlayın.")
        return

    cfg = active_watches[chat_id]
    ret = cfg.get("return_date") or "Tek yön"

    await update.message.reply_text(
        f"📡 Aktif Takip\n\n"
        f"🛫 {cfg['origin']} → {cfg['destination']}\n"
        f"📅 Gidiş: {cfg['depart_date']}\n"
        f"📅 Dönüş: {ret}\n"
        f"👥 Yolcu: {cfg['passengers']}"
    )


async def stop_watch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    if chat_id in active_watches:
        del active_watches[chat_id]
        await update.message.reply_text("🛑 Takip durduruldu.")
    else:
        await update.message.reply_text("📭 Aktif takip bulunamadı.")


async def check_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    if chat_id not in active_watches:
        await update.message.reply_text("📭 Önce /watch ile takip başlatın.")
        return

    await update.message.reply_text("🔍 Fiyatlar kontrol ediliyor...")
    await do_price_check(context.application, chat_id, active_watches[chat_id])


async def do_price_check(app: Application, chat_id: int, cfg: dict):
    try:
        results = await search_flights(
            origin=cfg["origin"],
            destination=cfg["destination"],
            depart_date=cfg["depart_date"],
            return_date=cfg.get("return_date"),
            passengers=cfg["passengers"],
        )

        msg = format_price_message(results, cfg)
        await app.bot.send_message(chat_id=chat_id, text=msg)

    except Exception as e:
        error_text = str(e)

        if "API Hatası 502" in error_text:
            friendly_message = (
                "⚠️ Uçuş sağlayıcısı şu anda geçici olarak yanıt vermiyor.\n"
                "Lütfen birkaç dakika sonra tekrar deneyin."
            )
        elif "API Hatası 403" in error_text:
            friendly_message = (
                "⚠️ API erişim veya abonelik sorunu var.\n"
                "RapidAPI aboneliğini ve anahtarını kontrol edin."
            )
        elif "API Hatası 404" in error_text:
            friendly_message = (
                "⚠️ API endpoint bulunamadı.\n"
                "Kullandığımız RapidAPI endpoint bilgisini tekrar kontrol etmek gerekiyor."
            )
        else:
            friendly_message = (
                f"⚠️ Fiyat kontrolü sırasında hata oluştu:\n{error_text}"
            )

        logger.exception("Price check error")
        await app.bot.send_message(
            chat_id=chat_id,
            text=friendly_message
        )


async def scheduled_check(context: ContextTypes.DEFAULT_TYPE):
    logger.info("Hourly check running for %s watches...", len(active_watches))

    for chat_id, cfg in list(active_watches.items()):
        await do_price_check(context.application, chat_id, cfg)


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ İşlem iptal edildi.")
    return ConversationHandler.END


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable is not set!")

    app = Application.builder().token(token).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("watch", watch_start)],
        states={
            ORIGIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_origin)],
            DESTINATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_destination)],
            DEPART_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_depart_date)],
            RETURN_DATE: [
                CallbackQueryHandler(get_return_date, pattern="^(roundtrip|oneway)$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_return_date_text),
            ],
            PASSENGERS: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_passengers)],
            CONFIRM: [CallbackQueryHandler(confirm_watch, pattern="^confirm_")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("list", list_watches))
    app.add_handler(CommandHandler("stop", stop_watch))
    app.add_handler(CommandHandler("check", check_now))

    app.job_queue.run_repeating(
        scheduled_check,
        interval=3600,
        first=10,
        name="hourly_price_check"
    )

    logger.info("Bot başlatılıyor...")
    app.run_polling()


if __name__ == "__main__":
    main()
