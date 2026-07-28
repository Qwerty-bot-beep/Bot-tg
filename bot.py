# bot.py – без лишних логов в консоли

import asyncio
import json
import os
import html
import pyotp
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# Устанавливаем уровень логирования WARNING – будут видны только ошибки
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

BOT_TOKEN = "8744765549:AAFyqZ-ucVEdfktvtl9mWMRS_CPflMi7mro"  # замените на свой

WHITELIST_FILE = "whitelist.json"
CONFIG_FILE = "config.json"

monitoring_paused = False
accounts_data = []

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ---------- FSM состояния ----------
class AddDeviceState(StatesGroup):
    waiting_for_device_name = State()
    waiting_for_2fa_code = State()

# ---------- Вспомогательные функции ----------
def load_whitelist():
    if os.path.exists(WHITELIST_FILE):
        with open(WHITELIST_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_whitelist(wh):
    with open(WHITELIST_FILE, "w", encoding="utf-8") as f:
        json.dump(wh, f, indent=2, ensure_ascii=False)

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)

def get_totp_secret():
    cfg = load_config()
    return cfg.get("totp_secret", "")

def set_totp_secret(secret):
    cfg = load_config()
    cfg["totp_secret"] = secret
    save_config(cfg)

def is_2fa_enabled():
    return bool(get_totp_secret())

def verify_totp(code):
    secret = get_totp_secret()
    if not secret:
        return True
    totp = pyotp.TOTP(secret)
    return totp.verify(code)

def set_accounts_whitelist(accounts):
    global accounts_data
    accounts_data = accounts

# ---------- КОМАНДЫ ----------
@dp.message(Command("start"), StateFilter("*"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    # Логирование убрано, чтобы не засорять консоль
    await message.answer(
        "<b>🛡️ Страж сессий</b> – бот для управления защитой.\n\n"
        "Команды:\n"
        "/status – статус программы\n"
        "/whitelist – список доверенных устройств\n"
        "/add &lt;устройство&gt; – добавить устройство (требует 2FA, если включена)\n"
        "/remove &lt;устройство&gt; – удалить устройство\n"
        "/pause – приостановить мониторинг\n"
        "/resume – возобновить мониторинг\n"
        "/log – последние 5 событий\n"
        "/setup_2fa – настроить Google Authenticator\n"
        "/accounts – список аккаунтов\n"
        "/cancel – отменить текущее действие",
        parse_mode="HTML"
    )

@dp.message(Command("help"))
async def cmd_help(message: types.Message, state: FSMContext):
    await cmd_start(message, state)

@dp.message(Command("status"))
async def cmd_status(message: types.Message):
    status = "⏸ Приостановлен" if monitoring_paused else "▶ Активен"
    await message.answer(
        f"<b>📊 Статус:</b> {status}\n<b>Аккаунтов:</b> {len(accounts_data)}",
        parse_mode="HTML"
    )

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
            await message.answer(
                f"ℹ️ Устройство '{device_name}' уже есть.",
                parse_mode="HTML"
            )
            await state.clear()
            return
        wh.append({"device": device_name})
        save_whitelist(wh)
        await message.answer(
            f"✅ Устройство '<b>{device_name}</b>' добавлено (2FA отключена).",
            parse_mode="HTML"
        )
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
            await message.answer(
                f"ℹ️ Устройство '{device_name}' уже есть.",
                parse_mode="HTML"
            )
            await state.clear()
            return
        wh.append({"device": device_name})
        save_whitelist(wh)
        await message.answer(
            f"✅ Устройство '<b>{device_name}</b>' добавлено (2FA подтверждена).",
            parse_mode="HTML"
        )
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
        await message.answer(
            f"❌ Устройство '{device_name}' не найдено.",
            parse_mode="HTML"
        )
        return
    save_whitelist(new_wh)
    await message.answer(
        f"✅ Устройство '{device_name}' удалено.",
        parse_mode="HTML"
    )

@dp.message(Command("pause"))
async def cmd_pause(message: types.Message):
    global monitoring_paused
    monitoring_paused = True
    await message.answer("⏸ Мониторинг приостановлен.")

@dp.message(Command("resume"))
async def cmd_resume(message: types.Message):
    global monitoring_paused
    monitoring_paused = False
    await message.answer("▶️ Мониторинг возобновлён.")

@dp.message(Command("log"))
async def cmd_log(message: types.Message):
    log_file = "guard.log"
    if not os.path.exists(log_file):
        await message.answer("ℹ️ Лог-файл ещё не создан.")
        return
    with open(log_file, "r", encoding="utf-8") as f:
        lines = f.readlines()
        last_lines = lines[-5:] if len(lines) >= 5 else lines
        escaped_lines = [html.escape(line) for line in last_lines]
        log_text = "\n".join(escaped_lines)
        await message.answer(
            f"<b>📄 Последние события:</b>\n{log_text}",
            parse_mode="HTML"
        )

@dp.message(Command("setup_2fa"))
async def cmd_setup_2fa(message: types.Message):
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
    if not accounts_data:
        await message.answer("ℹ️ Аккаунты не настроены.")
        return
    text = "<b>📋 Список аккаунтов:</b>\n"
    for idx, acc in enumerate(accounts_data, 1):
        text += f"{idx}. {acc.get('name', 'Без имени')} – {acc.get('PHONE_NUMBER', '')}\n"
    await message.answer(text, parse_mode="HTML")

@dp.message(Command("cancel"))
async def cmd_cancel(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("✅ Действие отменено.")

# ---------- ЗАПУСК БОТА ----------
async def bot_polling():
    print("🤖 Бот запущен и готов к работе.")  # оставляем для информации о запуске
    await dp.start_polling(bot)

def is_monitoring_paused():
    return monitoring_paused

def set_accounts_whitelist(accounts):
    global accounts_data
    accounts_data = accounts

def is_2fa_enabled():
    return bool(get_totp_secret())

def verify_totp(code):
    secret = get_totp_secret()
    if not secret:
        return True
    totp = pyotp.TOTP(secret)
    return totp.verify(code)