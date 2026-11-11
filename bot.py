import asyncio
import html
import logging
import os
import sqlite3
from datetime import datetime, timedelta, timezone

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "").strip().lstrip("@")
DB_PATH = os.getenv("DB_PATH", "belov_vpn.sqlite3")

PLANS = {
    "30": ("30 дней", 149),
    "90": ("90 дней", 399),
    "180": ("180 дней", 699),
}

logging.basicConfig(level=logging.INFO)
db = sqlite3.connect(DB_PATH, check_same_thread=False)
db.execute("""CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    username TEXT,
    plan_days INTEGER NOT NULL,
    amount INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL
)""")
db.execute("""CREATE TABLE IF NOT EXISTS access (
    user_id INTEGER PRIMARY KEY,
    vpn_link TEXT NOT NULL,
    expires_at TEXT NOT NULL
)""")
db.commit()

dp = Dispatcher()


def main_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="🛍 Купить VPN", callback_data="buy")
    kb.button(text="🔑 Мой VPN", callback_data="myvpn")
    kb.button(text="🧾 Мои заказы", callback_data="orders")
    kb.button(text="🆘 Поддержка", callback_data="support")
    kb.adjust(2, 2)
    return kb.as_markup()


def plans_menu():
    kb = InlineKeyboardBuilder()
    for key, (label, price) in PLANS.items():
        kb.button(text=f"{label} · {price} ₽", callback_data=f"plan:{key}")
    kb.button(text="⬅️ Назад", callback_data="home")
    kb.adjust(1)
    return kb.as_markup()


def contact_admin_menu():
    kb = InlineKeyboardBuilder()
    if SUPPORT_USERNAME:
        kb.button(text="👤 Перейти в профиль администратора", url=f"https://t.me/{SUPPORT_USERNAME}")
    kb.button(text="⬅️ В главное меню", callback_data="home")
    kb.adjust(1)
    return kb.as_markup()


@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "🇩🇪 <b>Belov | VPN</b>\n\n"
        "Добро пожаловать! Выберите действие в меню.\n\n"
        "Доступ выдаётся после ручного подтверждения заказа администратором.",
        reply_markup=main_menu(),
        parse_mode="HTML"
    )


@dp.callback_query(F.data == "home")
async def home(call: CallbackQuery):
    await call.message.edit_text("🇩🇪 <b>Belov | VPN</b>\nВыберите действие:", reply_markup=main_menu(), parse_mode="HTML")
    await call.answer()


@dp.callback_query(F.data == "buy")
async def buy(call: CallbackQuery):
    await call.message.edit_text("Выберите тариф:", reply_markup=plans_menu())
    await call.answer()


@dp.callback_query(F.data.startswith("plan:"))
async def choose_plan(call: CallbackQuery, bot: Bot):
    key = call.data.split(":", 1)[1]
    if key not in PLANS:
        await call.answer("Неизвестный тариф", show_alert=True)
        return
    days = int(key)
    label, price = PLANS[key]
    cur = db.execute(
        "INSERT INTO orders(user_id, username, plan_days, amount, status, created_at) VALUES(?,?,?,?,?,?)",
        (call.from_user.id, call.from_user.username or "", days, price, "pending", datetime.now(timezone.utc).isoformat())
    )
    order_id = cur.lastrowid
    db.commit()

    await call.message.edit_text(
        f"🧾 <b>Заказ №{order_id}</b>\n"
        f"Тариф: {label}\nСтоимость: {price} ₽\n\n"
        "✅ Заказ создан! Для оплаты и подтверждения свяжитесь с администратором. "
        "Нажмите кнопку ниже, чтобы открыть его Telegram-профиль. "
        "Также можете написать сообщение прямо сюда, и администратор его получит.",
        reply_markup=contact_admin_menu(),
        parse_mode="HTML"
    )
    if ADMIN_ID:
        username = f"@{call.from_user.username}" if call.from_user.username else "нет username"
        await bot.send_message(
            ADMIN_ID,
            f"🆕 Заказ №{order_id}\nПользователь: {call.from_user.full_name} ({username})\n"
            f"Telegram ID: <code>{call.from_user.id}</code>\nТариф: {label}\nСумма: {price} ₽\n"
            f"Выдать после проверки оплаты: /give {call.from_user.id} {days} {order_id} <VLESS_ССЫЛКА>",
            parse_mode="HTML"
        )
    await call.answer("Заказ создан")


@dp.callback_query(F.data == "myvpn")
async def myvpn(call: CallbackQuery):
    row = db.execute("SELECT vpn_link, expires_at FROM access WHERE user_id=?", (call.from_user.id,)).fetchone()
    if not row:
        text = "У вас пока нет активного доступа. Оформите заказ в разделе «Купить VPN»."
    else:
        text = f"🔑 Ваша ссылка:\n<code>{row[0]}</code>\n\nДействует до: {row[1]}"
    await call.message.answer(text, parse_mode="HTML")
    await call.answer()


@dp.callback_query(F.data == "orders")
async def orders(call: CallbackQuery):
    rows = db.execute(
        "SELECT id, plan_days, amount, status, created_at FROM orders WHERE user_id=? ORDER BY id DESC LIMIT 10",
        (call.from_user.id,)
    ).fetchall()
    if not rows:
        text = "У вас пока нет заказов."
    else:
        lines = ["🧾 <b>Ваши последние заказы:</b>"]
        for r in rows:
            lines.append(f"№{r[0]} · {r[1]} дней · {r[2]} ₽ · {r[3]}")
        text = "\n".join(lines)
    await call.message.answer(text, parse_mode="HTML")
    await call.answer()


@dp.callback_query(F.data == "support")
async def support(call: CallbackQuery):
    text = f"По вопросам заказа напишите @{SUPPORT_USERNAME}." if SUPPORT_USERNAME else "По вопросам заказа свяжитесь с администратором."
    await call.message.answer(text, reply_markup=contact_admin_menu())
    await call.answer()


@dp.message(Command("reply"))
async def reply_to_customer(message: Message, bot: Bot):
    """Администратор отвечает покупателю командой /reply USER_ID текст."""
    if message.from_user.id != ADMIN_ID:
        return
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        await message.answer("Формат: /reply USER_ID текст сообщения")
        return
    try:
        user_id = int(parts[1])
        reply_text = parts[2].strip()
        if not reply_text:
            raise ValueError()
        await bot.send_message(user_id, "💬 <b>Сообщение от администратора Belov VPN:</b>\n\n" + html.escape(reply_text), parse_mode="HTML")
        await message.answer("✅ Сообщение отправлено покупателю.")
    except ValueError:
        await message.answer("Проверьте USER_ID и текст сообщения.")
    except Exception as e:
        logging.exception("Не удалось отправить ответ покупателю")
        await message.answer(f"Не удалось отправить сообщение: {e}")


@dp.message(Command("give"))
async def give_access(message: Message):
    """Формат: /give USER_ID ДНЕЙ ORDER_ID VLESS_ССЫЛКА"""
    if message.from_user.id != ADMIN_ID:
        return
    parts = message.text.split(maxsplit=4)
    if len(parts) != 5:
        await message.answer("Формат: /give USER_ID ДНЕЙ ORDER_ID VLESS_ССЫЛКА")
        return
    try:
        user_id = int(parts[1])
        days = int(parts[2])
        order_id = int(parts[3])
        link = parts[4].strip()
    except ValueError:
        await message.answer("USER_ID, ДНЕЙ и ORDER_ID должны быть числами.")
        return

    if days not in (30, 90, 180):
        await message.answer("Срок должен быть 30, 90 или 180 дней.")
        return
    if not link.startswith(("vless://", "https://")):
        await message.answer("Ссылка должна начинаться с vless:// или https://")
        return

    # Проверяем, что заказ принадлежит этому пользователю и ещё не выдан
    row = db.execute("SELECT status FROM orders WHERE id=? AND user_id=?", (order_id, user_id)).fetchone()
    if not row:
        await message.answer("Заказ с таким ID не найден у этого пользователя.")
        return
    if row[0] == "approved":
        await message.answer("Этот заказ уже был выдан.")
        return

    now = datetime.now(timezone.utc)
    existing = db.execute("SELECT expires_at FROM access WHERE user_id=?", (user_id,)).fetchone()

    # Продлеваем срок, если есть активный доступ, иначе считаем от текущего момента
    if existing:
        try:
            current_expires = datetime.fromisoformat(existing[0])
        except ValueError:
            current_expires = now
        base = current_expires if current_expires > now else now
        expires = (base + timedelta(days=days)).isoformat()
    else:
        expires = (now + timedelta(days=days)).isoformat()

    db.execute(
        "INSERT INTO access(user_id, vpn_link, expires_at) VALUES(?,?,?) "
        "ON CONFLICT(user_id) DO UPDATE SET vpn_link=excluded.vpn_link, expires_at=excluded.expires_at",
        (user_id, link, expires)
    )
    db.execute("UPDATE orders SET status='approved' WHERE id=? AND user_id=?", (order_id, user_id))
    db.commit()

    await message.bot.send_message(
        user_id,
        f"✅ Доступ выдан на {days} дней!\n\nВаша ссылка:\n<code>{link}</code>\n\nДействует до: {expires}",
        parse_mode="HTML"
    )
    await message.answer(f"Доступ по заказу №{order_id} отправлен пользователю.")


@dp.message(Command("pending"))
async def pending(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    rows = db.execute(
        "SELECT id,user_id,plan_days,amount,created_at FROM orders WHERE status='pending' ORDER BY id DESC LIMIT 20"
    ).fetchall()
    if not rows:
        await message.answer("Ожидающих заказов нет.")
        return
    lines = ["Ожидающие заказы:"]
    for r in rows:
        lines.append(f"№{r[0]} · user {r[1]} · {r[2]} дней · {r[3]} ₽ · {r[4]}")
    await message.answer("\n".join(lines))


@dp.message()
async def customer_message(message: Message, bot: Bot):
    """Сообщения покупателей передаются администратору."""
    if message.from_user.id == ADMIN_ID:
        await message.answer("Чтобы написать покупателю, используй команду:\n/reply USER_ID текст сообщения")
        return
    if not ADMIN_ID:
        return

    user = message.from_user
    username = f"@{user.username}" if user.username else "нет username"
    header = (
        "📩 <b>Сообщение от покупателя</b>\n"
        f"Имя: {html.escape(user.full_name)}\n"
        f"Username: {html.escape(username)}\n"
        f"Telegram ID: <code>{user.id}</code>\n\n"
        "Чтобы ответить, отправьте команду:\n"
        f"<code>/reply {user.id} ваш текст</code>"
    )
    await bot.send_message(ADMIN_ID, header, parse_mode="HTML")
    try:
        await message.copy_to(ADMIN_ID)
        await message.answer("✅ Сообщение отправлено администратору. Ожидайте ответа.")
    except Exception:
        logging.exception("Не удалось передать сообщение администраторам")
        await message.answer("Не получилось отправить сообщение. Попробуйте ещё раз позже.")


async def main():
    if not BOT_TOKEN or not ADMIN_ID:
        raise RuntimeError("Заполните BOT_TOKEN и ADMIN_ID в переменных окружения.")
    bot = Bot(BOT_TOKEN)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
