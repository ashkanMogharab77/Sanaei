import os
import json
import re
import logging
import time
import asyncio
import boto3
import requests
from botocore.client import Config
from botocore.exceptions import ClientError
from telethon import TelegramClient, events, Button
from dotenv import load_dotenv
from yt_dlp import YoutubeDL

# ========== تنظیمات لاگ ==========
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ========== تنظیمات اولیه========
load_dotenv()
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
DOWNLOAD_FOLDER = os.getenv("DOWNLOAD_FOLDER")
Users = json.loads(os.getenv("USERS"))
YOUTUBE_REGEX = os.getenv("YOUTUBE_REGEX")
URL_REGEX = os.getenv("URL_REGEX")

if not os.path.exists(DOWNLOAD_FOLDER):
    os.makedirs(DOWNLOAD_FOLDER)


def clean_filename(filename):
    """پاک کردن کاراکترهای غیرمجاز از اسم فایل"""
    name, ext = os.path.splitext(filename)
    name = re.sub(r'[<>:"/\\|?*]', '', name)
    name = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', name)
    name = name.strip()
    name = name.replace(" ", "_")
    if len(name) > 80:
        name = name[:80]
    if not name:
        name = f"file"
    return f"{name}{ext}"


def get_content_type(filename):
    """تشخیص نوع فایل برای تنظیم صحیح Content-Type"""
    ext = os.path.splitext(filename)[1].lower()
    content_types = {
        '.pdf': 'application/pdf',
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.png': 'image/png',
        '.gif': 'image/gif',
        '.mp3': 'audio/mpeg',
        '.mp4': 'video/mp4',
        '.zip': 'application/zip',
        '.rar': 'application/x-rar-compressed',
        '.txt': 'text/plain',
        '.html': 'text/html',
        '.css': 'text/css',
        '.js': 'application/javascript',
        '.json': 'application/json',
        '.xml': 'application/xml',
    }
    return content_types.get(ext, 'application/octet-stream')


async def run_async(func, *args, **kwargs):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: func(*args, **kwargs))


def sync_download_url(url, local_path):
    with requests.get(url, stream=True, timeout=45) as r:
        r.raise_for_status()
        with open(local_path, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)


def upload_to_arvancloud(file_path, ARVAN_ACCESS_KEY, ARVAN_SECRET_KEY, ARVAN_ENDPOINT, ARVAN_BUCKET):
    try:
        original_name = os.path.basename(file_path)
        file_size = os.path.getsize(file_path) / (1024 * 1024)

        name, ext = os.path.splitext(original_name)
        timestamp = int(time.time())

        s3_file_key = f"{name}_{timestamp}{ext}"

        logger.info(f"شروع آپلود: {s3_file_key} ({file_size:.1f} MB)")

        s3_client = boto3.client(
            's3',
            endpoint_url=ARVAN_ENDPOINT,
            aws_access_key_id=ARVAN_ACCESS_KEY,
            aws_secret_access_key=ARVAN_SECRET_KEY,
            config=Config(
                signature_version='s3v4',
                connect_timeout=60,
                read_timeout=300
            )
        )

        s3_client.upload_file(
            file_path,
            ARVAN_BUCKET,
            s3_file_key,
            ExtraArgs={
                'ACL': 'public-read',
                'ContentType': get_content_type(original_name)
            }
        )

        region = ARVAN_ENDPOINT.replace(
            "https://s3.", "").replace(".arvanstorage.ir", "")
        file_url = f"https://{ARVAN_BUCKET}.s3.{region}.arvanstorage.ir/{s3_file_key}"

        logger.info(f"آپلود موفق: {file_url}")
        return True, f"✅ فایل با موفقیت در ArvanCloud آپلود شد!\n\n📁 نام: {s3_file_key}\n📦 حجم: {file_size:.1f} MB\n\n🔗 لینک دانلود مستقیم:\n{file_url}"

    except ClientError as e:
        error_code = e.response['Error']['Code']
        error_msg = e.response['Error']['Message']
        logger.error(f"خطای S3: {error_code} - {error_msg}")

        if error_code == 'AccessDenied':
            return False, "❌ خطای دسترسی! لطفاً تنظیمات Public Access باکت را بررسی کن."
        elif error_code == 'NoSuchBucket':
            return False, f"❌ باکت '{ARVAN_BUCKET}' وجود ندارد. لطفاً ابتدا باکت را بساز."
        else:
            return False, f"❌ خطای آپلود: {error_msg}"
    except Exception as e:
        logger.error(f"خطای ناشناخته: {e}")
        return False, f"❌ خطا: {str(e)[:150]}"


def test_arvancloud_connection(ARVAN_ACCESS_KEY, ARVAN_SECRET_KEY, ARVAN_ENDPOINT, ARVAN_BUCKET):
    """تست اتصال به ArvanCloud"""
    try:
        s3_client = boto3.client(
            's3',
            endpoint_url=ARVAN_ENDPOINT,
            aws_access_key_id=ARVAN_ACCESS_KEY,
            aws_secret_access_key=ARVAN_SECRET_KEY,
            config=Config(signature_version='s3v4')
        )
        buckets = s3_client.list_buckets()
        bucket_names = [b['Name'] for b in buckets['Buckets']]

        if ARVAN_BUCKET in bucket_names:
            logger.info(
                f"✅ اتصال به ArvanCloud برقرار است. باکت '{ARVAN_BUCKET}' یافت شد.")
            return True
        else:
            logger.warning(
                f"⚠️ باکت '{ARVAN_BUCKET}' یافت نشد. باکت‌های موجود: {bucket_names}")
            return False
    except Exception as e:
        logger.error(f"❌ خطا در تست اتصال: {e}")
        return False


def sync_extract_info(ydl_opts, text):
    with YoutubeDL(ydl_opts) as ydl:
        return ydl.extract_info(text, download=False)


def sync_download_youtube(ydl_opts, video_url):
    with YoutubeDL(ydl_opts) as ydl:
        info_download = ydl.extract_info(video_url, download=True)
        return ydl.prepare_filename(info_download)


# ========== راه‌اندازی ربات ==========
client = TelegramClient('bot_session', API_ID,
                        API_HASH).start(bot_token=BOT_TOKEN)


@client.on(events.NewMessage(pattern='/start'))
async def start(event):
    telegramid = event.chat_id
    result = True if telegramid in [user["chat_id"]
                                    for user in Users] else False
    if not result:
        await event.reply("🚫 شما مجاز به استفاده از ربات نیستید.")
        return
    await event.reply(
        "🤖 **ربات دانلودر**\n\n"
        "📌 **طریقه استفاده:**\n"
        "• یک فایل تلگرامی ارسال یا فوروارد کنید.\n"
        "• یک **لینک مستقیم دانلود یا ویدیو یوتوب** بفرستید.\n"
    )


@client.on(events.NewMessage)
async def download_file(event):
    msg = event.message
    text = msg.text.strip() if msg.text else ""

    if text.startswith('/start'):
        return

    telegramid = event.chat_id
    result = next(((user["ARVAN_ACCESS_KEY"], user["ARVAN_SECRET_KEY"], user["ARVAN_ENDPOINT"], user["ARVAN_BUCKET"])
                  for user in Users if user["chat_id"] == telegramid), (None, None, None, None))

    if result != (None, None, None, None):
        ARVAN_ACCESS_KEY, ARVAN_SECRET_KEY, ARVAN_ENDPOINT, ARVAN_BUCKET = result
    else:
        await event.reply("🚫 شما مجاز به استفاده از ربات نیستید.")
        return

    await run_async(test_arvancloud_connection, ARVAN_ACCESS_KEY, ARVAN_SECRET_KEY, ARVAN_ENDPOINT, ARVAN_BUCKET)

    try:
        if text.startswith('/'):
            return

        # الف) اگر پیام حاوی لینک یوتیوب بود
        if text and re.match(YOUTUBE_REGEX, text):
            status = await event.reply("🔍 **در حال استخراج کیفیت‌های موجود از یوتیوب...**")
            try:
                ydl_opts = {'quiet': True}
                info = await run_async(sync_extract_info, ydl_opts, text)
                video_id = info.get('id')

                buttons = [
                    [
                        Button.inline(
                            "🎬 1080p (Best HD)", data=f"yt:{video_id}:bestvideo[height<=1080]+bestaudio/best"),
                        Button.inline(
                            "🎥 720p (HD)", data=f"yt:{video_id}:bestvideo[height<=720]+bestaudio/best")
                    ],
                    [
                        Button.inline(
                            "📺 480p", data=f"yt:{video_id}:bestvideo[height<=480]+bestaudio/best"),
                        Button.inline(
                            "📱 360p (Low)", data=f"yt:{video_id}:bestvideo[height<=360]+bestaudio/best")
                    ],
                    [Button.inline("🎵 فقط صدا (Audio)",
                                   data=f"yt:{video_id}:bestaudio/best")]
                ]
                await status.edit("👇 **لطفاً کیفیت مد نظر خود را انتخاب کنید:**", buttons=buttons)
                return
            except Exception as ye:
                await status.edit(f"❌ **خطا در دریافت اطلاعات یوتیوب:**\n`{str(ye)[:100]}`")
                return

        # ب) اگر پیام حاوی لینک دانلود مستقیم معمولی بود
        elif text and re.match(URL_REGEX, text):
            status = await event.reply("📥 **در حال دانلود فایل از لینک مستقیم...**")
            try:
                url_path = text.split('?')[0]
                original_name = url_path.split('/')[-1]
                file_name = clean_filename(
                    original_name) if original_name else f"file.bin"
                local_path = os.path.join(DOWNLOAD_FOLDER, file_name)

                await run_async(sync_download_url, text, local_path)

                await process_upload(status, local_path, file_name, telegramid, ARVAN_ACCESS_KEY, ARVAN_SECRET_KEY, ARVAN_ENDPOINT, ARVAN_BUCKET)
            except Exception as ue:
                await status.edit(f"❌ **خطا در دانلود لینک مستقیم:**\n`{str(ue)[:100]}`")
            return

        # ج) اگر پیام یک فایل مدیا یا داکیومنت تلگرامی بود
        elif msg.media and msg.document:
            attrs = msg.document.attributes
            original_name = next(
                (a.file_name for a in attrs if hasattr(a, 'file_name')), None)
            file_name = clean_filename(
                original_name) if original_name else f"file.bin"
            file_size_mb = msg.document.size / (1024 * 1024)

            status = await event.reply(
                f"📥 **در حال دانلود فایل از تلگرام...**\n\n📄 نام: {file_name}\n📦 حجم: {file_size_mb:.1f} MB"
            )

            local_path = os.path.join(DOWNLOAD_FOLDER, file_name)
            await client.download_media(msg, file=local_path)
            await process_upload(status, local_path, file_name, telegramid, ARVAN_ACCESS_KEY, ARVAN_SECRET_KEY, ARVAN_ENDPOINT, ARVAN_BUCKET)

    except Exception as e:
        logger.error(f"خطا در پردازش کلی: {e}")


@client.on(events.CallbackQuery(pattern=r'^yt:'))
async def youtube_callback(event):
    telegramid = event.chat_id
    result = next(((user["ARVAN_ACCESS_KEY"], user["ARVAN_SECRET_KEY"], user["ARVAN_ENDPOINT"], user["ARVAN_BUCKET"])
                  for user in Users if user["chat_id"] == telegramid), (None, None, None, None))

    if result == (None, None, None, None):
        await event.answer("🚫 شما مجاز نیستید.", alert=True)
        return

    ARVAN_ACCESS_KEY, ARVAN_SECRET_KEY, ARVAN_ENDPOINT, ARVAN_BUCKET = result

    data_parts = event.data.decode('utf-8').split(':')
    video_id = data_parts[1]
    selected_format = data_parts[2]
    video_url = f"https://www.youtube.com/watch?v={video_id}"

    await event.edit("⏳ **کیفیت تایید شد. در حال دانلود ویدیو از یوتیوب...**\n(این فرآیند ممکن است کمی زمان‌بر باشد)")

    try:
        ydl_opts_info = {'quiet': True}
        info = await run_async(sync_extract_info, ydl_opts_info, video_url)
        title = info.get('title', f"video_{video_id}")

        cleaned_title = re.sub(r'[<>:"/\\|?*]', '', title)
        cleaned_title = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', cleaned_title)
        cleaned_title = cleaned_title.strip().replace(" ", "-")
        if len(cleaned_title) > 80:
            cleaned_title = cleaned_title[:80]

        custom_filename = f"{cleaned_title}.%(ext)s"

        ydl_opts = {
            'outtmpl': os.path.join(DOWNLOAD_FOLDER, custom_filename),
            'format': selected_format,
            'quiet': True,
            'merge_output_format': 'mp4'
        }

        local_path = await run_async(sync_download_youtube, ydl_opts, video_url)

        if not os.path.exists(local_path):
            base, _ = os.path.splitext(local_path)
            local_path = base + ".mp4"

        file_name = os.path.basename(local_path)

        await process_upload(event, local_path, file_name, telegramid, ARVAN_ACCESS_KEY, ARVAN_SECRET_KEY, ARVAN_ENDPOINT, ARVAN_BUCKET)

    except Exception as e:
        logger.error(f"خطا در دانلود یوتیوب: {e}")
        await event.edit(f"❌ **خطا در دانلود یوتیوب:**\n`{str(e)[:150]}`")


# ----------------- تابع حذف ناهمگام کمکی -----------------
async def _delete_file_after_delay(path, delay=300):
    """این تابع در پس‌زمینه اجرا شده، ۵ دقیقه منتظر می‌ماند و فایل را بدون معطل کردن بات حذف می‌کند"""
    await asyncio.sleep(delay)
    try:
        if os.path.exists(path):
            os.remove(path)
            logger.info(
                f"فایل محلی با موفقیت بعد از {delay} ثانیه حذف شد: {path}")
    except Exception as e:
        logger.error(f"خطا در حذف فایل دیلی خورده: {e}")


# ----------------- ۳. تابع کمکی آپلود و حذف فایل -----------------
async def process_upload(event_or_status, local_path, file_name, telegramid, access_key, secret_key, endpoint, bucket):
    if local_path and os.path.exists(local_path):
        final_size = os.path.getsize(local_path) / (1024 * 1024)

        await event_or_status.edit(
            f"✅ **دانلود کامل شد!**\n\n"
            f"📄 نام: {file_name}\n"
            f"📦 حجم: {final_size:.1f} MB\n\n"
            f"⏫ **در حال آپلود به ArvanCloud...**",
            buttons=None
        )

        success, result_msg = await run_async(
            upload_to_arvancloud, local_path, access_key, secret_key, endpoint, bucket
        )

        if success:
            await event_or_status.edit(f"{result_msg}\n")
        else:
            await event_or_status.edit(f"{result_msg}")

        client.loop.create_task(_delete_file_after_delay(local_path, 300))
        logger.info(
            f"حذف فایل {file_name} برای ۵ دقیقه دیگر در پس‌زمینه زمان‌بندی شد.")

        logger.info(
            f"کاربر {telegramid} - فایل: {file_name} - {final_size:.1f} MB - {'OK' if success else 'FAIL'}")


def main():
    client.run_until_disconnected()


if __name__ == "__main__":
    main()
