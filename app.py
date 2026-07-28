# app.py – бот для хостинга (без guard.py)
# Система регистрации устройства: при первом запуске генерируется код,
# который нужно отправить боту командой /register.

import asyncio
import json
import os
import html
import hashlib
import uuid
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# Настройка логирования (для отладки на сервере)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------- КОНФИГУРАЦИЯ ----------
BOT_TOKEN = "8744765549:AAFyqZ-ucVEdfktvtl9mWMRS_CPflMi7mro"  # замените на свой
WHITELIST_FILE = "whitelist.json"
ALLOWED_USERS_FILE = "allowed_users.json"
DEVICE_ID_FILE = "device_id.txt"
CONFIG_FILE = "config.json"  # для 2FA (опционально)

# ---------- ИНИЦИАЛИЗАЦИЯ БОТА ----------
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ---------- FSM для добавления устройства ----------
class AddDeviceState(StatesGroup):
    waiting_for_device_name = State()
    waiting_for_2fa_code = State()

# ---------- ГЕНЕРАТОР ID УСТРОЙСТВА ----------
def get_device_id():
    """Генерирует или загружает уникальный ID устройства."""
    if os.path.exists(DEVICE_ID_FILE):
        with open(DEVICE_ID_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    # Создаём новый ID на основе MAC-адреса и соли
    try:
        mac = uuid.getnode()
        salt = os.urandom(16).hex()
        device_id = hashlib.sha256(f"{mac}{salt}".encode()).hexdigest()[:16]
    except:
        device_id = str(uuid.uuid4())[:16]
    with open(DEVICE_ID_FILE, "w", encoding="utf-8") as f:
        f.write(device_id)
    return device_id

CURRENT_DEVICE_ID = get_device_id()
logger.info(f"🔑 ID устройства: {CURRENT_DEVICE_ID}")

# ---------- РАБОТА С БЕЛЫМ СПИСКОМ ----------
def load_whitelist():
    if os.path.exists(WHITELIST_FILE):
        with open(WHITELIST_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_whitelist(wh):
    with open(WHITELIST_FILE, "w", encoding="utf-8") as f:
        json.dump(wh, f, indent=2, ensure_ascii=False)

# ---------- РАБОТА С РЕГИСТРАЦИЕЙ ----------
def load_allowed_users():
    if os.path.exists(ALLOWED_USERS_FILE):
        with open(ALLOWED_USERS_FILE, "r") as f:
            return json.load(f)
    return []

def save_allowed_users(users):
    with open(ALLOWED_USERS_FILE, "w") as f:
        json.dump(users, f, indent=2)

def is_user_allowed(telegram_id):
    return str(telegram_id) in load_allowed_users()

# ---------- 2FA (опционально) ----------
def get_totp_secret():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            data = json.load(f)
            return data.get("totp_secret", "")
    return ""

def set_totp_secret(secret):
    data = {}
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            data = json.load(f)
    data["totp_secret"] = secret
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=2)

def is_2fa_enabled():
    return bool(get_totp_secret())

def verify_totp(code):
    import pyotp
    secret = get_totp_secret()
    if not secret:
        return True
    totp = pyotp.TOTP(secret)
    return totp.verify(code)

# ---------- MIDDLEWARE ДЛЯ ПРОВЕРКИ РЕГИСТРАЦИИ ----------
async def access_middleware(handler, event, data):
    user = data.get("event_from_user")
    if user:
        text = getattr(event, "text", "")
        if text and text.startswith("/register"):
            return await handler(event, data)
        if not is_user_allowed(user.id):
            await event.answer("⛔ Доступ запрещён. Сначала зарегистрируйте устройство: /register <код>")
            return
    return await handler(event, data)

dp.message.middleware(access_middleware)

# ---------- КОМАНДЫ БОТА ----------
@dp.message(Command("register"))
async def cmd_register(message: types.Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("❌ Укажите код: /register <код>")
        return
    code = args[1].strip()
    if code != CURRENT_DEVICE_ID:
        await message.answer("❌ Неверный код. Проверьте device_id.txt или перезапустите программу.")
        return
    users = load_allowed_users()
    if str(message.from_user.id) not in users:
        users.append(str(message.from_user.id))
        save_allowed_users(users)
        await message.answer("✅ Устройство успешно зарегистрировано! Теперь вы можете управлять программой.")
    else:
        await message.answer("ℹ️ Вы уже зарегистрированы.")

@dp.message(Command("start"), StateFilter("*"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "<b>🛡️ Страж сессий</b> – бот для управления защитой.\n\n"
        "Команды:\n"
        "/status – статус программы (заглушка)\n"
        "/whitelist – список доверенных устройств\n"
        "/add &lt;устройство&gt; – добавить устройство\n"
        "/remove &lt;устройство&gt; – удалить устройство\n"
        "/pause – приостановить мониторинг (заглушка)\n"
        "/resume – возобновить мониторинг (заглушка)\n"
        "/log – последние 5 событий (заглушка)\n"
        "/setup_2fa – настроить Google Authenticator\n"
        "/accounts – список аккаунтов (заглушка)\n"
        "/cancel – отменить текущее действие",
        parse_mode="HTML"
    )

@dp.message(Command("status"))
async def cmd_status(message: types.Message):
    # Заглушка, так как статус мониторинга не управляется ботом (он отдельно)
    await message.answer("📊 Бот работает. Мониторинг сессий запущен отдельно.")

@dp.message(Command("whitelist"))
async def cmd_whitelist(message: types.Message):
    wh = load_whitelist()
    if not wh:
        await message.answer("📋 Белый список пуст.")
        return
    devices = "\n".join([f"- {item['device']}" for item in wh])
    await message.answer(
        f"<b>📋 Белый список:</b>\n{devices}",
        parse_mode="HTML"
    )

@dp.message(Command("add"))
async def cmd_add_start(message: types.Message, state: FSMContext):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("❌ Укажите устройство: /add Название")
        return
    device_name = args[1].strip()
    await state.update_data(device_name=device_name)
    if is_2fa_enabled():
        await message.answer(
            "🔐 2FA включена. Введите код из Google Authenticator для подтверждения:",
            parse_mode="HTML"
        )
        await state.set_state(AddDeviceState.waiting_for_2fa_code)
    else:
        wh = load_whitelist()
        if any(item['device'].lower() == device_name.lower() for item in wh):
            await message.answer(f"ℹ️ Устройство '{device_name}' уже есть.")
            await state.clear()
            return
        wh.append({"device": device_name})
        save_whitelist(wh)
        await message.answer(f"✅ Устройство '{device_name}' добавлено.")
        await state.clear()

@dp.message(AddDeviceState.waiting_for_2fa_code)
async def process_2fa_code(message: types.Message, state: FSMContext):
    code = message.text.strip()
    if not code.isdigit() or len(code) != 6:
        await message.answer("❌ Код должен состоять из 6 цифр. Попробуйте снова:")
        return
    if verify_totp(code):
        data = await state.get_data()
        device_name = data.get("device_name")
        wh = load_whitelist()
        if any(item['device'].lower() == device_name.lower() for item in wh):
            await message.answer(f"ℹ️ Устройство '{device_name}' уже есть.")
            await state.clear()
            return
        wh.append({"device": device_name})
        save_whitelist(wh)
        await message.answer(f"✅ Устройство '{device_name}' добавлено (2FA подтверждена).")
        await state.clear()
    else:
        await message.answer("❌ Неверный код. Попробуйте снова (или /cancel).")

@dp.message(Command("remove"))
async def cmd_remove(message: types.Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("❌ Укажите устройство: /remove Название")
        return
    device_name = args[1].strip()
    wh = load_whitelist()
    new_wh = [item for item in wh if item['device'].lower() != device_name.lower()]
    if len(new_wh) == len(wh):
        await message.answer(f"❌ Устройство '{device_name}' не найдено.")
        return
    save_whitelist(new_wh)
    await message.answer(f"✅ Устройство '{device_name}' удалено.")

@dp.message(Command("pause"))
async def cmd_pause(message: types.Message):
    # Заглушка, так как управление мониторингом осуществляется через guard.py
    await message.answer("⏸ Мониторинг приостановлен (заглушка).")

@dp.message(Command("resume"))
async def cmd_resume(message: types.Message):
    await message.answer("▶️ Мониторинг возобновлён (заглушка).")

@dp.message(Command("log"))
async def cmd_log(message: types.Message):
    await message.answer("ℹ️ Логи доступны только в основном приложении.")

@dp.message(Command("setup_2fa"))
async def cmd_setup_2fa(message: types.Message):
    import pyotp
    secret = pyotp.random_base32()
    set_totp_secret(secret)
    totp = pyotp.TOTP(secret)
    provisioning_uri = totp.provisioning_uri(
        message.from_user.username or "user",
        issuer_name="SessionGuard"
    )
    await message.answer(
        f"<b>🔐 Настройка 2FA</b>\n\n"
        f"Ваш секрет: <code>{secret}</code>\n"
        f"Используйте его в Google Authenticator.\n"
        f"Или отсканируйте QR-код по ссылке:\n"
        f"{provisioning_uri}\n\n"
        f"Теперь при добавлении устройств потребуется код подтверждения.",
        parse_mode="HTML"
    )

@dp.message(Command("accounts"))
async def cmd_accounts(message: types.Message):
    await message.answer("ℹ️ Список аккаунтов доступен только в основном приложении.")

@dp.message(Command("cancel"))
async def cmd_cancel(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("✅ Действие отменено.")

# ---------- ЗАПУСК БОТА ----------
async def main():
    logger.info("🤖 Бот запущен и готов к работе.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())