import os
import logging
import requests
import tempfile
import asyncio
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    CallbackQueryHandler
)
import google.generativeai as genai
from moviepy.editor import ImageClip, concatenate_videoclips, AudioFileClip, TextClip, CompositeVideoClip

# إعدادات البوت من متغيرات البيئة
TOKEN = os.getenv('TOKEN')
ADMIN_ID = int(os.getenv('ADMIN_ID'))
CHANNEL_USERNAME = os.getenv('CHANNEL_USERNAME')

# إعداد التسجيل
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# تخزين بيانات المستخدمين
user_data = {}

# مسار لحفظ حالة المستخدمين (للاستمرارية)
DATA_FILE = "user_data.json"

# تحميل بيانات المستخدمين من ملف
def load_user_data():
    global user_data
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, 'r') as f:
                user_data = json.load(f)
                logger.info("✅ تم تحميل بيانات المستخدمين")
    except Exception as e:
        logger.error(f"خطأ في تحميل البيانات: {e}")

# حفظ بيانات المستخدمين إلى ملف
def save_user_data():
    try:
        with open(DATA_FILE, 'w') as f:
            json.dump(user_data, f)
        logger.info("💾 تم حفظ بيانات المستخدمين")
    except Exception as e:
        logger.error(f"خطأ في حفظ البيانات: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data[str(user_id)] = {"step": "start", "api_keys": {}}
    save_user_data()
    
    keyboard = [
        [InlineKeyboardButton("Gemini API", callback_data="set_gemini")],
        [InlineKeyboardButton("Leonardo API", callback_data="set_leonardo")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🪄 *مرحبًا بك في بوت صناعة الفيديوهات بالذكاء الاصطناعي!*\n\n"
        "🌟 قم بإنشاء فيديو احترافي من أي نص في ثوانٍ\n\n"
        "🔑 *الخطوة الأولى:* تحتاج لإضافة مفاتيح API التالية:\n\n"
        "1. `Google Gemini API` - لتحويل النص لوصف مرئي\n"
        "2. `Leonardo AI API` - لإنشاء الصور\n\n"
        "اختر المفتاح الذي تريد إضافته:",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    if query.data.startswith("set_"):
        api_type = query.data.split("_")[1]
        user_data[str(user_id)]["step"] = f"waiting_{api_type}_api"
        save_user_data()
        
        await query.edit_message_text(
            f"🔑 *أرسل مفتاح {api_type.upper()} API الآن*\n\n"
            f"📎 روابط الحصول على المفاتيح:\n"
            f"{get_api_links(api_type)}\n\n"
            "⚠️ سيتم التحقق من صحة المفتاح تلقائيًا",
            parse_mode="Markdown"
        )

def get_api_links(api_type):
    links = {
        "gemini": "• [Google Gemini API](https://aistudio.google.com/app/apikey)",
        "leonardo": "• [Leonardo AI API](https://app.leonardo.ai/account)",
    }
    return links.get(api_type, "")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    
    if str(user_id) not in user_data:
        await start(update, context)
        return
    
    current_step = user_data[str(user_id)].get("step", "")
    
    if "waiting_" in current_step:
        api_type = current_step.split("_")[1]
        user_data[str(user_id)]["api_keys"][api_type] = text
        user_data[str(user_id)]["step"] = "start"
        save_user_data()
        
        is_valid = await validate_api_key(api_type, text)
        
        if is_valid:
            await update.message.reply_text(f"✅ *تم حفظ {api_type.upper()} API بنجاح!*", parse_mode="Markdown")
            await check_apis_ready(update, context, user_id)
        else:
            await update.message.reply_text(f"❌ *مفتاح غير صحيح!* أرسل مفتاح صحيح لـ {api_type.upper()} API", parse_mode="Markdown")
    
    elif user_data[str(user_id)].get("apis_ready", False):
        if len(text) < 10:
            await update.message.reply_text("❌ النص قصير جدًا! أرسل نصًا يحتوي على 10 كلمات على الأقل")
            return
            
        await create_video(update, context, text)
    else:
        await start(update, context)

async def validate_api_key(api_type, key):
    try:
        if api_type == "gemini":
            genai.configure(api_key=key)
            model = genai.GenerativeModel('gemini-pro')
            model.generate_content("Test")
            return True
            
        elif api_type == "leonardo":
            url = "https://cloud.leonardo.ai/api/rest/v1/me"
            headers = {"Authorization": f"Bearer {key}"}
            response = requests.get(url, headers=headers)
            return response.status_code == 200
        
    except Exception as e:
        logger.error(f"Validation error: {e}")
        return False

async def check_apis_ready(update, context, user_id):
    required_apis = ["gemini", "leonardo"]
    if all(api in user_data[str(user_id)]["api_keys"] for api in required_apis):
        user_data[str(user_id)]["apis_ready"] = True
        save_user_data()
        
        await context.bot.send_message(
            chat_id=user_id,
            text="🎉 *تم تفعيل جميع مفاتيح API بنجاح!*\n\n"
                 "أرسل لي الآن النص الذي تريد تحويله إلى فيديو\n\n"
                 "مثال: \"منظر لغروب الشمس على شاطئ البحر مع أمواج هادئة وطيور تحلق في السماء\"",
            parse_mode="Markdown"
        )

async def check_membership(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        member = await context.bot.get_chat_member(
            chat_id=CHANNEL_USERNAME,
            user_id=update.effective_user.id
        )
        return member.status in ["member", "administrator", "creator"]
    except Exception as e:
        logger.error(f"Membership error: {e}")
        return False

async def create_video(update: Update, context: ContextTypes.DEFAULT_TYPE, user_text: str):
    user_id = update.effective_user.id
    
    # التحقق من الاشتراك في القناة
    if not await check_membership(update, context):
        keyboard = [[InlineKeyboardButton("انضم للقناة", url=f"https://t.me/{CHANNEL_USERNAME[1:]}")]]
        await update.message.reply_text(
            "⛔ *يجب الاشتراك في القناة أولاً لاستخدام البوت*\n\n"
            "اشترك ثم أعد إرسال النص",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return
    
    # إعلام المستخدم ببدء المعالجة
    processing_msg = await update.message.reply_text("🔄 *جاري معالجة طلبك...*\n\n⏳ قد تستغرق العملية 2-3 دقائق", parse_mode="Markdown")
    
    try:
        # 1. إنشاء وصف مرئي باستخدام Gemini
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=processing_msg.message_id,
            text="🔄 *جاري معالجة طلبك...*\n\n🚀 المرحلة 1/3: إنشاء وصف مرئي"
        )
        
        gemini_api = user_data[str(user_id)]["api_keys"]["gemini"]
        genai.configure(api_key=gemini_api)
        model = genai.GenerativeModel('gemini-pro')
        
        response = model.generate_content(
            f"أنشئ وصفًا مرئيًا مفصلًا لإنشاء فيديو من هذا النص: {user_text}"
        )
        visual_description = response.text
        
        # 2. إنشاء الصور باستخدام Leonardo
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=processing_msg.message_id,
            text="🔄 *جاري معالجة طلبك...*\n\n🚀 المرحلة 2/3: إنشاء الصور (قد تستغرق 60 ثانية)"
        )
        
        leonardo_api = user_data[str(user_id)]["api_keys"]["leonardo"]
        images = []
        for i in range(3):
            img_data = await generate_leonardo_image(visual_description, leonardo_api)
            images.append(img_data)
        
        # 3. إنشاء الفيديو
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=processing_msg.message_id,
            text="🔄 *جاري معالجة طلبك...*\n\n🚀 المرحلة 3/3: تجميع الفيديو"
        )
        
        video_path = await generate_video(images, user_text)
        
        # 4. إرسال الفيديو
        await context.bot.send_video(
            chat_id=update.effective_chat.id,
            video=open(video_path, 'rb'),
            caption="🎬 *تم إنشاء الفيديو بنجاح!*\n\n"
                    "👍 استمتع بالفيديو\n"
                    "🔄 لإعادة إنشاء فيديو جديد أرسل نصًا آخر",
            parse_mode="Markdown"
        )
        
    except Exception as e:
        logger.error(f"Error: {e}")
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=processing_msg.message_id,
            text="❌ *حدث خطأ أثناء المعالجة!*\n\n"
                 "السبب المحتمل:\n"
                 "- مفتاح API غير صالح\n"
                 "- مشكلة في اتصال الإنترنت\n"
                 "- النص غير مناسب\n\n"
                 "الرجاء المحاولة مرة أخرى"
        )
    finally:
        try:
            await context.bot.delete_message(
                chat_id=update.message.chat_id,
                message_id=processing_msg.message_id
            )
        except Exception:
            pass

async def generate_leonardo_image(prompt: str, api_key: str) -> bytes:
    """إنشاء صورة باستخدام Leonardo API"""
    url = "https://cloud.leonardo.ai/api/rest/v1/generations"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "prompt": prompt[:1000],  # تقليل الطول لتجنب الأخطاء
        "modelId": "ac614f96-1082-45bf-be9d-757f2d31c174",
        "width": 1024,
        "height": 576
    }
    
    response = requests.post(url, json=payload, headers=headers)
    response.raise_for_status()
    generation_id = response.json()["sdGenerationJob"]["generationId"]
    
    # انتظر حتى تكتمل الصورة
    await asyncio.sleep(45)
    
    url = f"https://cloud.leonardo.ai/api/rest/v1/generations/{generation_id}"
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    
    image_url = response.json()["generations_by_pk"]["generated_images"][0]["url"]
    img_response = requests.get(image_url)
    return img_response.content

async def generate_video(images: list, text: str) -> str:
    """إنشاء فيديو متطور"""
    clips = []
    temp_dir = tempfile.mkdtemp()
    
    # إضافة صوت
    tts_url = f"https://translate.google.com/translate_tts?ie=UTF-8&tl=ar&client=tw-ob&q={text[:300]}"
    audio_response = requests.get(tts_url)
    audio_path = os.path.join(temp_dir, "audio.mp3")
    with open(audio_path, "wb") as f:
        f.write(audio_response.content)
    
    audio_clip = AudioFileClip(audio_path)
    
    # معالجة الصور
    for i, img_data in enumerate(images):
        img_path = os.path.join(temp_dir, f"scene_{i}.jpg")
        with open(img_path, "wb") as f:
            f.write(img_data)
        
        img_clip = ImageClip(img_path).set_duration(audio_clip.duration / len(images))
        
        # إضافة نص للمشهد
        txt_clip = TextClip(
            text[:100],
            fontsize=40,
            color="white",
            font="Arial-Bold",
            stroke_color="black",
            stroke_width=1,
            size=(img_clip.w * 0.9, None)
        ).set_position(("center", "bottom")).set_duration(img_clip.duration)
        
        final_clip = CompositeVideoClip([img_clip, txt_clip])
        clips.append(final_clip)
    
    # دمج الفيديو
    final_video = concatenate_videoclips(clips)
    final_video = final_video.set_audio(audio_clip)
    
    video_path = os.path.join(temp_dir, "output.mp4")
    final_video.write_videofile(video_path, fps=24, codec="libx264", audio_codec="aac")
    
    return video_path

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إحصائيات البوت للمشرف"""
    if update.effective_user.id != ADMIN_ID:
        return
        
    users_count = len(user_data)
    await update.message.reply_text(
        f"📊 *إحصائيات البوت*\n\n"
        f"👤 عدد المستخدمين: {users_count}",
        parse_mode="Markdown"
    )

def main():
    # تحميل بيانات المستخدمين عند البدء
    load_user_data()
    
    # إنشاء تطبيق البوت
    application = Application.builder().token(TOKEN).build()
    
    # معالجات الأوامر
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stats", admin_stats))
    
    # معالجات الرسائل
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # معالجات الأزرار
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # بدء البوت
    logger.info(f"✅ البوت يعمل الآن! | المشرف: {ADMIN_ID}")
    application.run_polling()

if __name__ == "__main__":
    main()