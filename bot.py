
import asyncio
import logging
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from html import escape

from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery, Update
from aiogram.utils.keyboard import InlineKeyboardBuilder

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "").strip().lstrip("@")
DB_PATH = os.getenv("DB_PATH", "belov_vpn.sqlite3")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()
BASE_URL = (
    os.getenv("WEBHOOK_URL", "").strip()
    or os.getenv("RENDER_EXTERNAL_URL", "").strip()
)
PORT = int(os.getenv("PORT", "10000"))

PLANS = {
    "30": ("30 дней", 70),
    "90": ("90 дней", 190),
    "180": ("180 дней", 400),
}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

db = sqlite3.connect(DB_PATH)
db.execute("""
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    username TEXT,
    plan_days INTEGER NOT NULL,
    amount INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL
)
""")
db.execute("""
CREATE TABLE IF NOT EXISTS access (
    user_id INTEGER PRIMARY KEY,
    vpn_link TEXT NOT NULL,
    expires_at TEXT NOT NULL
)
""")
db.commit()

dp = Dispatcher()
bot = None


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
        kb.button(
            text=f"{label} · {price} ₽",
            callback_data=f"plan:{key}"
        )
    kb.button(text="⬅️ Назад", callback_data="home")
    kb.adjust(1)
    return kb.as_markup()


@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "🇩🇪 <b>Belov | VPN</b>\n\n"
        "Добро пожаловать! Выберите действие.",
        reply_markup=main_menu()
    )


@dp.callback_query(F.data == "home")
async def home(call: CallbackQuery):
    await call.message.edit_text(
        "🇩🇪 <b>Belov | VPN</b>\nВыберите действие:",
        reply_markup=main_menu()
    )
    await call.answer()


@dp.callback_query(F.data == "buy")
async def buy(call: CallbackQuery):
    await call.message.edit_text(
        "Выберите тариф:",
        reply_markup=plans_menu()
    )
    await call.answer()


@dp.callback_query(F.data.startswith("plan:"))
async def choose_plan(call: CallbackQuery):
    key = call.data.split(":", 1)[1]

    if key not in PLANS:
        await call.answer("Неизвестный тариф", show_alert=True)
        return

    days = int(key)
    label, price = PLANS[key]

    cur = db.execute(
        """INSERT INTO orders
        (user_id, username, plan_days, amount, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?)""",
        (
            call.from_user.id,
            call.from_user.username or "",
            days,
            price,
            "pending",
            datetime.now(timezone.utc).isoformat()
        )
    )
    order_id = cur.lastrowid
    db.commit()

    await call.message.edit_text(
        f"🧾 <b>Заказ №{order_id}</b>\n"
        f"Тариф: {label}\n"
        f"Стоимость: {price} ₽\n\n"
        "Заказ создан. Для оплаты и подтверждения "
        "свяжитесь с администратором.",
        reply_markup=main_menu()
    )

    if ADMIN_ID:
        username = (
            f"@{escape(call.from_user.username)}"
            if call.from_user.username
            else "нет username"
        )

        await call.bot.send_message(
            ADMIN_ID,
            f"🆕 Заказ №{order_id}\n"
            f"Пользователь: {escape(call.from_user.full_name)}\n"
            f"Username: {username}\n"
            f"Telegram ID: <code>{call.from_user.id}</code>\n"
            f"Тариф: {label}\n"
            f"Сумма: {price} ₽\n\n"
            f"После проверки оплаты можно выдать доступ командой:\n"
            f"/give {call.from_user.id} {days} VLESS_ССЫЛКА"
        )

    await call.answer("Заказ создан")


@dp.callback_query(F.data == "myvpn")
async def myvpn(call: CallbackQuery):
    row = db.execute(
        "SELECT vpn_link, expires_at FROM access WHERE user_id=?",
        (call.from_user.id,)
    ).fetchone()

    if not row:
        text = "У вас пока нет доступа. Оформите заказ."
    else:
        text = (
            f"🔑 Ваша ссылка:\n<code>{escape(row[0])}</code>\n\n"
            f"Действует до: {escape(row[1])}"
        )

    await call.message.answer(text)
    await call.answer()


@dp.callback_query(F.data == "orders")
async def orders(call: CallbackQuery):
    rows = db.execute(
        """SELECT id, plan_days, amount, status
        FROM orders WHERE user_id=?
        ORDER BY id DESC LIMIT 10""",
        (call.from_user.id,)
    ).fetchall()

    if not rows:
        text = "У вас пока нет заказов."
    else:
        lines = ["🧾 <b>Ваши заказы:</b>"]
        for row in rows:
            lines.append(
                f"№{row[0]} · {row[1]} дней · "
                f"{row[2]} ₽ · {row[3]}"
            )
        text = "\n".join(lines)

    await call.message.answer(text)
    await call.answer()


@dp.callback_query(F.data == "support")
async def support(call: CallbackQuery):
    if SUPPORT_USERNAME:
        text = f"Поддержка: @{escape(SUPPORT_USERNAME)}"
    else:
        text = "Свяжитесь с администратором."

    await call.message.answer(text)
    await call.answer()


@dp.message(Command("give"))
async def give_access(message: Message):
    if not message.from_user or message.from_user.id != ADMIN_ID:
        return

    parts = message.text.split(maxsplit=3)

    if len(parts) != 4:
        await message.answer(
            "Формат: /give USER_ID ДНЕЙ VLESS_ССЫЛКА"
        )
        return

    try:
        user_id = int(parts[1])
        days = int(parts[2])
        link = parts[3].strip()

        if days not in (30, 90, 180):
            raise ValueError()

        if not link.startswith(("vless://", "https://")):
            raise ValueError()

        expires = (
            datetime.now(timezone.utc) + timedelta(days=days)
        ).isoformat()

        db.execute(
            """INSERT INTO access(user_id, vpn_link, expires_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
            vpn_link=excluded.vpn_link,
            expires_at=excluded.expires_at""",
            (user_id, link, expires)
        )

        db.execute(
            """UPDATE orders SET status='approved'
            WHERE user_id=? AND status='pending'""",
            (user_id,)
        )
        db.commit()

        await message.bot.send_message(
            user_id,
            f"✅ Доступ выдан на {days} дней!\n\n"
            f"Ваша ссылка:\n<code>{escape(link)}</code>\n\n"
            f"Действует до: {expires}"
        )

        await message.answer("Доступ отправлен пользователю.")

    except (ValueError, TypeError):
        await message.answer(
            "Проверьте ID, срок и ссылку."
        )


@dp.message(Command("pending"))
async def pending(message: Message):
    if not message.from_user or message.from_user.id != ADMIN_ID:
        return

    rows = db.execute(
        """SELECT id, user_id, plan_days, amount
        FROM orders WHERE status='pending'
        ORDER BY id DESC LIMIT 20"""
    ).fetchall()

    if not rows:
        await message.answer("Ожидающих заказов нет.")
        return

    lines = ["Ожидающие заказы:"]
    for row in rows:
        lines.append(
            f"№{row[0]} · user {row[1]} · "
            f"{row[2]} дней · {row[3]} ₽"
        )

    await message.answer("\n".join(lines))


async def health(request):
    return web.Response(text="Belov VPN is running")


async def webhook(request):
    secret = request.headers.get(
        "X-Telegram-Bot-Api-Secret-Token", ""
    )

    if secret != WEBHOOK_SECRET:
        raise web.HTTPForbidden()

    try:
        data = await request.json()
        update = Update.model_validate(data, context={"bot": bot})
        await dp.feed_update(bot, update)
    except Exception:
        logger.exception("Webhook update failed")
        raise web.HTTPBadRequest()

    return web.Response(text="OK")


async def on_startup(app):
    webhook_url = BASE_URL.rstrip("/") + "/webhook"

    await bot.set_webhook(
        webhook_url,
        secret_token=WEBHOOK_SECRET
    )
    logger.info("Webhook configured")


async def on_cleanup(app):
    await bot.session.close()
    db.close()


async def main():
    global bot

    if not BOT_TOKEN or not ADMIN_ID:
        raise RuntimeError("Set BOT_TOKEN and ADMIN_ID")

    if not BASE_URL or not WEBHOOK_SECRET:
        raise RuntimeError(
            "Set RENDER_EXTERNAL_URL and WEBHOOK_SECRET"
        )

    bot = Bot(
        BOT_TOKEN,
        default=DefaultBotProperties(
            parse_mode=ParseMode.HTML
        )
    )

    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    app.router.add_post("/webhook", webhook)

    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()

    logger.info("Belov VPN web server started")

    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
