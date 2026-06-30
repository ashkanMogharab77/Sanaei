import jdatetime
import sqlite3
import json
import os

from datetime import timedelta
from dotenv import load_dotenv
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaVideo,
)

os.environ['ALL_PROXY'] = 'socks5h://RVmNZ7nUZu:sPsz0RYxMR@127.0.0.1:8443'
os.environ['HTTP_PROXY'] = 'socks5h://RVmNZ7nUZu:sPsz0RYxMR@127.0.0.1:8443'
os.environ['HTTPS_PROXY'] = 'socks5h://RVmNZ7nUZu:sPsz0RYxMR@127.0.0.1:8443'

load_dotenv()
token = os.getenv("TOKEN")
admin = int(os.getenv("ADMIN"))
sub_prefix = os.getenv("SUB_PREFIX")
users = json.loads(os.getenv("USERS"))
apps_by_os = json.loads(os.getenv("APPS_BY_OS"))
videos_prefix = os.getenv("VIDEOS_PREFIX")
videos_postfix = json.loads(os.getenv("VIDEOS_POSTFIX"))

telegram_app: Application = ApplicationBuilder().token(token).build()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegramid = update.effective_chat.id
    result = next(((user["name"], user["sub_link"])
                  for user in users if user["chat_id"] == telegramid), (None, None))

    if result != (None, None):
        name, sub_link = result
        conn = sqlite3.connect("/etc/x-ui/x-ui.db")
        cursor = conn.cursor()
        cursor.execute(
            "SELECT up, down, total, expiry_time FROM client_traffics WHERE email = ?", (name,))
        if cursor.fetchone() != None:
            up, down, total, expiry_time = cursor.fetchone()
            sum_usage = up + down
            up, down, sum_usage, total = (
                f"{val / (1024**3):.2f}GB" if val > 1024**3
                else f"{val / (1024**2):.2f}MB" if val > 1024**2
                else f"{val / 1024:.2f}KB" if val > 1024
                else f"{val}B" if val != 0
                else "0"
                for val in (up, down, sum_usage, total)
            )

            jalali_date = (jdatetime.datetime.fromtimestamp(
                expiry_time / 1000) + timedelta(hours=3, minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
            sub_link = sub_prefix + sub_link
            message = (
                f"\u200F🆔 نام کاربری: {name}\n"
                f"🔗 لینک اشتراک:\n\u200F{sub_link}\n\n"
                f"🔼 آپلود↑: {up}\n"
                f"🔽 دانلود↓: {down}\n"
                f"🔄 کل: {sum_usage} / {total}\n"
                f"📅 تاریخ انقضا: \u200E{jalali_date}"
            )
        else:
            message = f"اشتراک شما به پایان رسیده است"
        cursor.close()
        conn.close()
    else:
        message = "اطلاعاتی یافت نشد"

    await update.message.reply_text(message)


async def help_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegramid = update.effective_chat.id
    result = any(user["chat_id"] == telegramid for user in users)

    if result:
        keyboard = [
            [InlineKeyboardButton("دانلود برنامه مورد نیاز",
                                  callback_data="select_os")],
            [InlineKeyboardButton("نحوه اتصال به اشتراک",
                                  callback_data="select_video")],
        ]
        query = update.callback_query
        if query:
            await query.answer()
            await query.edit_message_text(
                text="در رابطه با کدام موضوع نیاز به راهنمایی دارید؟",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        else:
            await update.message.reply_text(
                "در رابطه با کدام موضوع نیاز به راهنمایی دارید؟",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

    else:
        await update.message.reply_text("اطلاعاتی یافت نشد")


async def select_os(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Android", callback_data="android_apps")],
        [InlineKeyboardButton("IOS", callback_data="ios_apps")],
        [InlineKeyboardButton("Windows", callback_data="windows_apps")],
        [InlineKeyboardButton("بازگشت", callback_data="back_to_help_menu")],
    ]
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("سیستم عامل خود را انتخاب کنید", reply_markup=InlineKeyboardMarkup(keyboard))


async def show_apps(update: Update, context: ContextTypes.DEFAULT_TYPE):

    selected_os = update.callback_query.data.split("_apps")[0]
    apps = apps_by_os[selected_os]
    keyboard = []
    for app in apps:
        name, link = app
        keyboard.append([InlineKeyboardButton(name, url=link)])

    keyboard.append([InlineKeyboardButton(
        "بازگشت", callback_data="select_os")])
    await update.callback_query.answer()
    await update.callback_query.edit_message_text(
        "برنامه مورد نظر خود را انتخاب کنید",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def select_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    message = query.message
    unique_apps = []
    seen = set()
    for apps in apps_by_os.values():
        for name, _ in apps:
            if name not in seen:
                seen.add(name)
                unique_apps.append(name)
    keyboard = []
    for unique_app in unique_apps:
        keyboard.append([InlineKeyboardButton(
            unique_app, callback_data=f"show_video_{unique_apps.index(unique_app)}")])
    keyboard.append([InlineKeyboardButton(
        "بازگشت", callback_data="back_to_help_menu")])

    if message.text == "برنامه مورد نظر خود را انتخاب کنید":
        await query.message.reply_text(
            "برنامه مورد نظر خود را انتخاب کنید",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await query.edit_message_text(
            "برنامه مورد نظر خود را انتخاب کنید",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )


async def show_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    index = int(query.data.split("show_video_")[-1])
    url = videos_prefix + videos_postfix[index]["link"]

    await query.edit_message_media(media=InputMediaVideo(media=url))
    await select_video(update, context)


async def send_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegramid = update.effective_chat.id

    if telegramid == admin:
        if context.args:
            notify_text = " ".join(context.args)
        else:
            await update.message.reply_text(
                "⚠️ لطفاً متن پیام رو هم بعد از دستور بنویسید.\nمثال:\n/notify سلام دوستان!"
            )
            return

        sent_count = 0
        failed_count = 0

        for user in users:
            if user["chat_id"] == telegramid:
                continue

            try:
                await context.bot.send_message(chat_id=user["chat_id"], text=notify_text)
                sent_count += 1
            except Exception as e:
                await context.bot.send_message(chat_id=admin, text=f"❌ خطا در ارسال به {user['chat_id']}")
                failed_count += 1

        message = f"✅ پیام برای {sent_count} کاربر ارسال شد."
        if failed_count:
            message += f"\n⚠️ {failed_count} ارسال ناموفق داشتیم."
    else:
        message = "اطلاعاتی یافت نشد"

    await update.message.reply_text(message)

telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(CommandHandler("help", help_menu))
telegram_app.add_handler(CommandHandler("notify", send_message))

telegram_app.add_handler(CallbackQueryHandler(
    select_os, pattern=r"^select_os$"))
telegram_app.add_handler(CallbackQueryHandler(
    show_apps, pattern=r"^(android|ios|windows)_apps$"))
telegram_app.add_handler(CallbackQueryHandler(
    select_video, pattern=r"^select_video"))
telegram_app.add_handler(CallbackQueryHandler(
    show_video, pattern=r"^show_video_\d+$"))
telegram_app.add_handler(CallbackQueryHandler(
    help_menu, pattern=r"^back_to_help_menu$"))

if __name__ == "__main__":
    telegram_app.run_polling(allowed_updates=Update.ALL_TYPES)
