import logging
import asyncio
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler
from motor.motor_asyncio import AsyncIOMotorClient

# --- CONFIGURATION ---
BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"
MONGO_URL = "YOUR_MONGODB_URL_HERE"
ADMIN_ID = 123456789 # သင့် Telegram ID ထည့်ပါ

# --- DATABASE SETUP ---
client = AsyncIOMotorClient(MONGO_URL)
db = client['anon_chat_db']
users_col = db['users']

# --- STATES ---
GENDER, MENU = range(2)

# --- LOGGING ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- HELPER FUNCTIONS ---
async def get_user(user_id):
    return await users_col.find_one({"user_id": user_id})

async def update_status(user_id, status):
    await users_col.update_one({"user_id": user_id}, {"$set": {"status": status}})

async def find_partner(user_id):
    # ကိုယ်မဟုတ်တဲ့၊ status 'searching' ဖြစ်နေတဲ့သူကို ရှာမယ်
    partner = await users_col.find_one({
        "status": "searching",
        "user_id": {"$ne": user_id}
    })
    return partner

# --- START & REGISTRATION ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    
    # User အသစ်လား စစ်မယ်
    existing_user = await get_user(user.id)
    if not existing_user:
        keyboard = [[KeyboardButton("👨 Male"), KeyboardButton("👩 Female")]]
        await update.message.reply_text(
            "👋 မင်္ဂလာပါ Anonymous Chat Bot က ကြိုဆိုပါတယ်။\n"
            "သူငယ်ချင်းအသစ်တွေရှာဖို့ သင့်ရဲ့ Gender ကို အရင်ရွေးပေးပါ။",
            reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
        )
        return GENDER
    else:
        # User အဟောင်းဆိုရင် Main Menu ပြမယ်
        await show_main_menu(update)
        return MENU

async def set_gender(update: Update, context: ContextTypes.DEFAULT_TYPE):
    gender = update.message.text
    user = update.effective_user
    
    if gender not in ["👨 Male", "👩 Female"]:
        await update.message.reply_text("ကျေးဇူးပြု၍ Button နှိပ်ပြီး ရွေးပေးပါ။")
        return GENDER

    # Database မှာ သိမ်းမယ်
    new_user = {
        "user_id": user.id,
        "first_name": user.first_name,
        "gender": gender,
        "status": "idle", # idle, searching, chatting
        "partner_id": None
    }
    await users_col.update_one({"user_id": user.id}, {"$set": new_user}, upsert=True)
    
    await update.message.reply_text(f"မှတ်တမ်းတင်ပြီးပါပြီ! {gender}")
    await show_main_menu(update)
    return MENU

async def show_main_menu(update: Update):
    keyboard = [
        [KeyboardButton("🔍 Find Partner"), KeyboardButton("👤 My Profile")]
    ]
    await update.message.reply_text(
        "အောက်ပါ Button တွေကို သုံးပြီး စကားစပြောနိုင်ပါပြီ။ 👇",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )

# --- MATCHING LOGIC ---
async def find_match_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.reply_text("🔍 Partner ရှာနေပါတယ်... ခဏစောင့်ပေးပါ...", reply_markup=ReplyKeyboardRemove())
    
    # ကိုယ့် status ကို searching ပြောင်းမယ်
    await update_status(user_id, "searching")
    
    # Partner ရှာမယ်
    partner = await find_partner(user_id)
    
    if partner:
        partner_id = partner['user_id']
        
        # ၂ ယောက်လုံးကို chatting status ပြောင်း၊ partner_id ချိတ်ပေး
        await users_col.update_one({"user_id": user_id}, {"$set": {"status": "chatting", "partner_id": partner_id}})
        await users_col.update_one({"user_id": partner_id}, {"$set": {"status": "chatting", "partner_id": user_id}})
        
        msg = "🎉 Partner တွေ့ပါပြီ! စကားစပြောနိုင်ပါပြီ။\n/next - လူပြောင်းမယ်\n/stop - စကားပြောရပ်မယ်"
        await context.bot.send_message(user_id, msg)
        await context.bot.send_message(partner_id, msg)
        
    else:
        # Partner မတွေ့သေးရင်
        await update.message.reply_text("⏳ လူစောင့်နေပါတယ်... လူတွေ့ရင် Bot က အကြောင်းကြားပါမယ်။")

# --- CHATTING LOGIC ---
async def message_relay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = await get_user(user_id)
    
    if not user_data:
        return # Register မလုပ်ရသေးရင် ဘာမှမလုပ်ဘူး
        
    status = user_data.get('status')
    partner_id = user_data.get('partner_id')

    # Menu Button နှိပ်တာတွေကို စစ်မယ်
    text = update.message.text
    if text == "🔍 Find Partner":
        await find_match_handler(update, context)
        return
    elif text == "👤 My Profile":
        await update.message.reply_text(f"👤 Name: {user_data.get('first_name')}\n⚧ Gender: {user_data.get('gender')}")
        return

    # Chatting ဖြစ်နေမှ တဖက်လူကို ပို့မယ်
    if status == "chatting" and partner_id:
        try:
            # Message အမျိုးအစားစုံ (Text, Photo, Sticker, etc.) ကို Copy လုပ်ပို့မယ်
            await update.message.copy(chat_id=partner_id)
        except Exception as e:
            # တဖက်လူက Block သွားရင်
            await context.bot.send_message(user_id, "⚠️ တဖက်လူက Chat ကို ပိတ်လိုက်ပုံရပါတယ်။ /next နှိပ်ပြီး အသစ်ရှာပါ။")
            await stop_chat(user_id, partner_id, context)
    elif status == "searching":
        await update.message.reply_text("🔍 ရှာနေတုန်းမို့ ခဏစောင့်ပါ။")
    else:
        await update.message.reply_text("စကားပြောဖို့ '🔍 Find Partner' ကို နှိပ်ပါ။")

# --- CONTROL COMMANDS ---
async def next_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = await get_user(user_id)
    
    if user_data['status'] == "chatting":
        partner_id = user_data['partner_id']
        await context.bot.send_message(partner_id, "❌ တဖက်လူက စကားဝိုင်းကို ကျော်သွားပါတယ်။\n/search နှိပ်ပြီး အသစ်ရှာပါ။")
        await stop_chat(user_id, partner_id, context)
    
    # ချက်ချင်း အသစ်ပြန်ရှာမယ်
    await find_match_handler(update, context)

async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = await get_user(user_id)
    
    if user_data['status'] == "chatting":
        partner_id = user_data['partner_id']
        await context.bot.send_message(partner_id, "❌ တဖက်လူက စကားပြောတာ ရပ်လိုက်ပါတယ်။")
        await stop_chat(user_id, partner_id, context)
        await show_main_menu(update)
    else:
        # Searching ဖြစ်နေရင် ရှာတာရပ်မယ်
        await update_status(user_id, "idle")
        await update.message.reply_text("🛑 ရှာဖွေခြင်းကို ရပ်လိုက်ပါပြီ။")
        await show_main_menu(update)

async def stop_chat(user1_id, user2_id, context):
    # ၂ ယောက်လုံးကို idle ပြောင်း၊ partner ဖျက်
    await users_col.update_one({"user_id": user1_id}, {"$set": {"status": "idle", "partner_id": None}})
    await users_col.update_one({"user_id": user2_id}, {"$set": {"status": "idle", "partner_id": None}})

# --- MAIN EXECUTION ---
if __name__ == '__main__':
    app = Application.builder().token(BOT_TOKEN).build()

    # Conversation Handler for Registration
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            GENDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_gender)],
            MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, message_relay)]
        },
        fallbacks=[CommandHandler('start', start)]
    )

    app.add_handler(conv_handler)
    
    # Commands
    app.add_handler(CommandHandler("next", next_chat))
    app.add_handler(CommandHandler("stop", stop_command))
    app.add_handler(CommandHandler("search", find_match_handler))
    
    # Message Handler (Chatting logic)
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, message_relay))

    print("Bot Started...")
    app.run_polling()