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
db = sqlite3.connect(DB_PATH)
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
db.execute("""CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    full_name TEXT,
    joined_at TEXT NOT NULL
)""")
db.commit()

dp = Dispatcher()


def is_admin(user_id: int) -> bool:
    return bool(ADMIN_ID) and user_id == ADMIN_ID


def register_user(user):
    db.execute(
        """INSERT INTO users(user_id, username, full_name, joined_at)
        VALUES(?,?,?,?)
        ON CONFLICT(user_id) DO UPDATE SET
        username=excluded.username, full_name=excluded.full_name""",
        (user.id, user.username or "", user.full_name or "",
         datetime.now(timezone.utc).isoformat())
    )
    db.commit()


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
        kb.button(text="👤 Перейти в профиль администратора",
                  url=f"https://t.me/{SUPPORT_USERNAME}")
    kb.button(text="⬅️ В главное меню", callback_data="home")
    kb.adjust(1)
    return kb.as_markup()


def admin_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="🧾 Заказы", callback_data="adm:orders")
    kb.button(text="👥 Пользователи", callback_data="adm:users")
    kb.button(text="📊 Статистика", callback_data="adm:stats")
    kb.button(text="💳 Тарифы и цены", callback_data="adm:prices")
    kb.button(text="🔑 Активные доступы", callback_data="adm:access")
    kb.button(text="📣 Как сделать рассылку", callback_data="adm:broadcast")
    kb.button(text="⬅️ В меню бота", callback_data="adm:home")
    kb.adjust(2, 2, 1, 1, 1)
    return kb.as_markup()


def admin_orders_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="🕓 Ожидают оплаты", callback_data="adm:orders:pending")
    kb.button(text="📚 Последние заказы", callback_data="adm:orders:all")
    kb.button(text="⬅️ В панель", callback_data="adm:panel")
    kb.adjust(1)
    return kb.as_markup()


async def show_admin_orders(target, status_filter="pending"):
    if status_filter == "pending":
        rows = db.execute(
            "SELECT id,user_id,plan_days,amount,status,created_at FROM orders "
            "WHERE status='pending' ORDER BY id DESC LIMIT 15"
        ).fetchall()
        heading = "🕓 <b>Заказы, ожидающие оплаты</b>"
    else:
        rows = db.execute(
            "SELECT id,user_id,plan_days,amount,status,created_at FROM orders "
            "ORDER BY id DESC LIMIT 15"
        ).fetchall()
        heading = "📚 <b>Последние заказы</b>"

    if not rows:
        text = heading + "\n\nЗаказов пока нет."
        markup = admin_orders_menu()
    else:
        lines = [heading]
        kb = InlineKeyboardBuilder()
        for order_id, user_id, days, amount, status, created_at in rows:
            lines.append(
                f"\n№{order_id} · ID <code>{user_id}</code>\n"
                f"{days} дней · {amount} ₽ · {html.escape(status)}"
            )
            if status == "pending":
                kb.button(text=f"Заказ №{order_id}", callback_data=f"adm:order:{order_id}")
        kb.button(text="⬅️ К заказам", callback_data="adm:orders")
        kb.adjust(1)
        text = "\n".join(lines)
        markup = kb.as_markup() if status_filter == "pending" else admin_orders_menu()

    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
        await target.answer()
    else:
        await target.answer(text, reply_markup=markup, parse_mode="HTML")


@dp.message(CommandStart())
async def start(message: Message):
    register_user(message.from_user)
    await message.answer(
        "🇩🇪 <b>Belov | VPN</b>\n\n"
        "Добро пожаловать! Выберите действие в меню.\n\n"
        "Доступ выдаётся после ручного подтверждения заказа администратором.",
        reply_markup=main_menu(),
        parse_mode="HTML"
    )


@dp.message(Command("admin"))
async def admin_command(message: Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer(
        "🛡 <b>Belov VPN | Админ-панель</b>\nВыберите раздел:",
        reply_markup=admin_menu(),
        parse_mode="HTML"
    )


@dp.callback_query(F.data.startswith("adm:"))
async def admin_callbacks(call: CallbackQuery, bot: Bot):
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        return

    data = call.data
    if data in ("adm:panel",):
        await call.message.edit_text(
            "🛡 <b>Belov VPN | Админ-панель</b>\nВыберите раздел:",
            reply_markup=admin_menu(), parse_mode="HTML"
        )
        await call.answer()
    elif data == "adm:home":
        await call.message.edit_text(
            "🇩🇪 <b>Belov | VPN</b>\nВыберите действие:",
            reply_markup=main_menu(), parse_mode="HTML"
        )
        await call.answer()
    elif data == "adm:orders":
        await call.message.edit_text(
            "🧾 <b>Управление заказами</b>\nВыберите список:",
            reply_markup=admin_orders_menu(), parse_mode="HTML"
        )
        await call.answer()
    elif data == "adm:orders:pending":
        await show_admin_orders(call, "pending")
    elif data == "adm:orders:all":
        await show_admin_orders(call, "all")
    elif data.startswith("adm:order:"):
        order_id = int(data.rsplit(":", 1)[1])
        row = db.execute(
            "SELECT id,user_id,username,plan_days,amount,status,created_at "
            "FROM orders WHERE id=?", (order_id,)
        ).fetchone()
        if not row:
            await call.answer("Заказ не найден", show_alert=True)
            return
        oid, user_id, username, days, amount, status, created_at = row
        text = (
            f"🧾 <b>Заказ №{oid}</b>\n"
            f"Клиент: <code>{user_id}</code>\n"
            f"Username: @{html.escape(username or '') if username else 'не указан'}\n"
            f"Тариф: {days} дней\nСумма: {amount} ₽\n"
            f"Статус: {html.escape(status)}\nСоздан: {html.escape(created_at)}\n\n"
            "Подтверждение отмечает оплату, но не выдаёт VPN автоматически."
        )
        kb = InlineKeyboardBuilder()
        if status == "pending":
            kb.button(text="✅ Подтвердить оплату", callback_data=f"adm:approve:{oid}")
            kb.button(text="❌ Отклонить", callback_data=f"adm:reject:{oid}")
        kb.button(text="👤 Карточка клиента", callback_data=f"adm:user:{user_id}")
        kb.button(text="⬅️ К заказам", callback_data="adm:orders:pending")
        kb.adjust(1)
        await call.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")
        await call.answer()
    elif data.startswith("adm:approve:"):
        order_id = int(data.rsplit(":", 1)[1])
        row = db.execute(
            "SELECT user_id FROM orders WHERE id=? AND status='pending'", (order_id,)
        ).fetchone()
        if not row:
            await call.answer("Заказ уже обработан или не найден", show_alert=True)
            return
        db.execute("UPDATE orders SET status='approved' WHERE id=?", (order_id,))
        db.commit()
        try:
            await bot.send_message(row[0], f"✅ Оплата заказа №{order_id} подтверждена.\nАдминистратор подготовит доступ VPN.")
        except Exception:
            pass
        await call.answer("Оплата отмечена")
        await call.message.edit_text(
            f"✅ Оплата заказа №{order_id} подтверждена.\nДля выдачи доступа используй /give {row[0]} ДНЕЙ VLESS_ССЫЛКА",
            reply_markup=admin_menu()
        )
    elif data.startswith("adm:reject:"):
        order_id = int(data.rsplit(":", 1)[1])
        row = db.execute(
            "SELECT user_id FROM orders WHERE id=? AND status='pending'", (order_id,)
        ).fetchone()
        if not row:
            await call.answer("Заказ уже обработан или не найден", show_alert=True)
            return
        db.execute("UPDATE orders SET status='rejected' WHERE id=?", (order_id,))
        db.commit()
        try:
            await bot.send_message(row[0], f"❌ Заказ №{order_id} отклонён. Если это ошибка, напишите в поддержку.")
        except Exception:
            pass
        await call.answer("Заказ отклонён")
        await call.message.edit_text("❌ Заказ отклонён.", reply_markup=admin_menu())
    elif data == "adm:users":
        rows = db.execute(
            "SELECT user_id,username,full_name,joined_at FROM users ORDER BY joined_at DESC LIMIT 15"
        ).fetchall()
        if not rows:
            text = "👥 Пользователей пока нет. Они появятся после запуска бота."
        else:
            lines = ["👥 <b>Последние пользователи</b>"]
            kb = InlineKeyboardBuilder()
            for uid, username, full_name, joined in rows:
                lines.append(
                    f"\n{html.escape(full_name or 'Без имени')} · "
                    f"<code>{uid}</code> · @{html.escape(username or 'нет username')}"
                )
                kb.button(text=f"Открыть {uid}", callback_data=f"adm:user:{uid}")
            kb.button(text="⬅️ В панель", callback_data="adm:panel")
            kb.adjust(1)
            await call.message.edit_text("\n".join(lines), reply_markup=kb.as_markup(), parse_mode="HTML")
            await call.answer()
            return
        await call.message.edit_text(text, reply_markup=admin_menu(), parse_mode="HTML")
        await call.answer()
    elif data.startswith("adm:user:"):
        user_id = int(data.rsplit(":", 1)[1])
        user = db.execute(
            "SELECT username,full_name,joined_at FROM users WHERE user_id=?", (user_id,)
        ).fetchone()
        access = db.execute(
            "SELECT expires_at FROM access WHERE user_id=?", (user_id,)
        ).fetchone()
        count, spent = db.execute(
            "SELECT COUNT(*),COALESCE(SUM(CASE WHEN status='approved' THEN amount ELSE 0 END),0) "
            "FROM orders WHERE user_id=?", (user_id,)
        ).fetchone()
        username, full_name, joined = user if user else ("", "Не найден", "неизвестно")
        text = (
            f"👤 <b>Клиент</b>\nИмя: {html.escape(full_name or 'Без имени')}\n"
            f"Username: @{html.escape(username or 'не указан')}\n"
            f"Telegram ID: <code>{user_id}</code>\n"
            f"Регистрация: {html.escape(joined)}\n"
            f"Заказов: {count}\nОплачено: {spent} ₽\n"
            f"VPN до: {html.escape(access[0] if access else 'доступ не выдан')}\n\n"
            f"Выдать/обновить доступ: /give {user_id} ДНЕЙ VLESS_ССЫЛКА"
        )
        kb = InlineKeyboardBuilder()
        kb.button(text="⬅️ К пользователям", callback_data="adm:users")
        kb.button(text="⬅️ В панель", callback_data="adm:panel")
        kb.adjust(1)
        await call.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")
        await call.answer()
    elif data == "adm:stats":
        users_count = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        total_orders = db.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        pending_count = db.execute("SELECT COUNT(*) FROM orders WHERE status='pending'").fetchone()[0]
        approved_count, revenue = db.execute(
            "SELECT COUNT(*),COALESCE(SUM(amount),0) FROM orders WHERE status='approved'"
        ).fetchone()
        active_count = db.execute(
            "SELECT COUNT(*) FROM access WHERE expires_at > ?", (datetime.now(timezone.utc).isoformat(),)
        ).fetchone()[0]
        text = (
            "📊 <b>Статистика Belov VPN</b>\n\n"
            f"👥 Пользователей: {users_count}\n"
            f"🧾 Всего заказов: {total_orders}\n"
            f"🕓 Ожидают оплаты: {pending_count}\n"
            f"✅ Оплачено заказов: {approved_count}\n"
            f"💰 Выручка по подтверждённым заказам: {revenue} ₽\n"
            f"🔑 Выдано доступов: {active_count}"
        )
        await call.message.edit_text(text, reply_markup=admin_menu(), parse_mode="HTML")
        await call.answer()
    elif data == "adm:prices":
        lines = ["💳 <b>Текущие тарифы</b>"]
        for key, (label, price) in PLANS.items():
            lines.append(f"{label}: {price} ₽")
        lines.append("\nИзменить цену: /price 30 149")
        lines.append("Доступные сроки: 30, 90, 180 дней.")
        await call.message.edit_text("\n".join(lines), reply_markup=admin_menu(), parse_mode="HTML")
        await call.answer()
    elif data == "adm:access":
        rows = db.execute(
            "SELECT user_id,expires_at FROM access ORDER BY expires_at DESC LIMIT 20"
        ).fetchall()
        if not rows:
            text = "🔑 Выданных доступов пока нет."
        else:
            lines = ["🔑 <b>Последние выданные доступы</b>"]
            for uid, expires in rows:
                lines.append(f"\nID <code>{uid}</code> · до {html.escape(expires)}")
            text = "\n".join(lines)
        await call.message.edit_text(text, reply_markup=admin_menu(), parse_mode="HTML")
        await call.answer()
    elif data == "adm:broadcast":
        await call.message.edit_text(
            "📣 <b>Рассылка</b>\n\nОтправь команду:\n"
            "<code>/broadcast Текст сообщения</code>\n"
            "Сообщение получат пользователи, которые запускали бота.",
            reply_markup=admin_menu(), parse_mode="HTML"
        )
        await call.answer()


@dp.callback_query(F.data == "home")
async def home(call: CallbackQuery):
    await call.message.edit_text(
        "🇩🇪 <b>Belov | VPN</b>\nВыберите действие:",
        reply_markup=main_menu(), parse_mode="HTML"
    )
    await call.answer()


@dp.callback_query(F.data == "buy")
async def buy(call: CallbackQuery):
    await call.message.edit_text("Выберите тариф:", reply_markup=plans_menu())
    await call.answer()


@dp.callback_query(F.data.startswith("plan:"))
async def choose_plan(call: CallbackQuery, bot: Bot):
    register_user(call.from_user)
    key = call.data.split(":", 1)[1]
    if key not in PLANS:
        await call.answer("Неизвестный тариф", show_alert=True)
        return
    days = int(key)
    label, price = PLANS[key]
    cur = db.execute(
        "INSERT INTO orders(user_id, username, plan_days, amount, status, created_at) "
        "VALUES(?,?,?,?,?,?)",
        (call.from_user.id, call.from_user.username or "", days, price, "pending",
         datetime.now(timezone.utc).isoformat())
    )
    order_id = cur.lastrowid
    db.commit()

    await call.message.edit_text(
        f"🧾 <b>Заказ №{order_id}</b>\n"
        f"Тариф: {label}\nСтоимость: {price} ₽\n\n"
        "✅ Заказ создан! Для оплаты и подтверждения свяжитесь с администратором. "
        "Нажмите кнопку ниже, чтобы открыть его Telegram-профиль.",
        reply_markup=contact_admin_menu(), parse_mode="HTML"
    )
    if ADMIN_ID:
        username = f"@{call.from_user.username}" if call.from_user.username else "нет username"
        await bot.send_message(
            ADMIN_ID,
            f"🆕 Заказ №{order_id}\nПользователь: {call.from_user.full_name} ({username})\n"
            f"Telegram ID: <code>{call.from_user.id}</code>\nТариф: {label}\nСумма: {price} ₽\n"
            f"Проверить заказ: /admin",
            parse_mode="HTML"
        )
    await call.answer("Заказ создан")


@dp.callback_query(F.data == "myvpn")
async def myvpn(call: CallbackQuery):
    row = db.execute(
        "SELECT vpn_link, expires_at FROM access WHERE user_id=?",
        (call.from_user.id,)
    ).fetchone()
    if not row:
        text = "У вас пока нет активного доступа. Оформите заказ в разделе «Купить VPN»."
    else:
        text = f"🔑 Ваша ссылка:\n<code>{html.escape(row[0])}</code>\n\nДействует до: {html.escape(row[1])}"
    await call.message.answer(text, parse_mode="HTML")
    await call.answer()


@dp.callback_query(F.data == "orders")
async def orders(call: CallbackQuery):
    rows = db.execute(
        "SELECT id, plan_days, amount, status, created_at FROM orders "
        "WHERE user_id=? ORDER BY id DESC LIMIT 10",
        (call.from_user.id,)
    ).fetchall()
    if not rows:
        text = "У вас пока нет заказов."
    else:
        lines = ["🧾 <b>Ваши последние заказы:</b>"]
        for r in rows:
            lines.append(f"№{r[0]} · {r[1]} дней · {r[2]} ₽ · {html.escape(r[3])}")
        text = "\n".join(lines)
    await call.message.answer(text, parse_mode="HTML")
    await call.answer()


@dp.callback_query(F.data == "support")
async def support(call: CallbackQuery):
    text = (
        f"По вопросам заказа напишите @{SUPPORT_USERNAME}."
        if SUPPORT_USERNAME else
        "По вопросам заказа свяжитесь с администратором."
    )
    await call.message.answer(text, reply_markup=contact_admin_menu())
    await call.answer()


@dp.message(Command("price"))
async def change_price(message: Message):
    if not is_admin(message.from_user.id):
        return
    parts = (message.text or "").split()
    if len(parts) != 3:
        await message.answer("Формат: /price 30 149\nСрок: 30, 90 или 180. Цена в рублях.")
        return
    key, raw_price = parts[1], parts[2]
    if key not in PLANS:
        await message.answer("Можно менять тарифы 30, 90 или 180 дней.")
        return
    try:
        price = int(raw_price)
        if not 1 <= price <= 100000:
            raise ValueError
    except ValueError:
        await message.answer("Цена должна быть целым числом от 1 до 100000.")
        return
    PLANS[key] = (PLANS[key][0], price)
    await message.answer(f"✅ Цена тарифа {PLANS[key][0]} изменена на {price} ₽.\nВажно: после перезапуска Render цена вернётся к значению в коде.")


@dp.message(Command("user"))
async def user_lookup(message: Message):
    if not is_admin(message.from_user.id):
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Формат: /user TELEGRAM_ID")
        return
    uid = int(parts[1])
    user = db.execute(
        "SELECT username,full_name,joined_at FROM users WHERE user_id=?", (uid,)
    ).fetchone()
    access = db.execute("SELECT expires_at FROM access WHERE user_id=?", (uid,)).fetchone()
    count, spent = db.execute(
        "SELECT COUNT(*),COALESCE(SUM(CASE WHEN status='approved' THEN amount ELSE 0 END),0) "
        "FROM orders WHERE user_id=?", (uid,)
    ).fetchone()
    if not user:
        await message.answer(f"Пользователь {uid} не найден в списке запусков бота.")
        return
    await message.answer(
        f"👤 {html.escape(user[1] or 'Без имени')}\n"
        f"Username: @{html.escape(user[0] or 'не указан')}\nID: <code>{uid}</code>\n"
        f"Заказов: {count}\nОплачено: {spent} ₽\n"
        f"VPN до: {html.escape(access[0] if access else 'доступ не выдан')}\n"
        f"Выдать доступ: /give {uid} ДНЕЙ VLESS_ССЫЛКА",
        parse_mode="HTML"
    )


@dp.message(Command("broadcast"))
async def broadcast(message: Message, bot: Bot):
    if not is_admin(message.from_user.id):
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await message.answer("Формат: /broadcast Текст сообщения")
        return
    recipients = [r[0] for r in db.execute("SELECT user_id FROM users").fetchall()]
    sent = failed = 0
    for uid in recipients:
        try:
            await bot.send_message(uid, parts[1])
            sent += 1
        except Exception:
            failed += 1
    await message.answer(f"📣 Рассылка завершена.\nОтправлено: {sent}\nНе доставлено: {failed}")


@dp.message(Command("reply"))
async def reply_to_customer(message: Message, bot: Bot):
    if not is_admin(message.from_user.id):
        return
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 3:
        await message.answer("Формат: /reply USER_ID текст сообщения")
        return
    try:
        user_id = int(parts[1])
        reply_text = parts[2].strip()
        if not reply_text:
            raise ValueError()
        await bot.send_message(
            user_id,
            "💬 <b>Сообщение от администратора Belov VPN:</b>\n\n" + html.escape(reply_text),
            parse_mode="HTML"
        )
        await message.answer("✅ Сообщение отправлено покупателю.")
    except ValueError:
        await message.answer("Проверьте USER_ID и текст сообщения.")
    except Exception:
        logging.exception("Не удалось отправить ответ покупателю")
        await message.answer("Не удалось отправить сообщение. Проверьте ID пользователя.")


@dp.message(Command("give"))
async def give_access(message: Message):
    if not is_admin(message.from_user.id):
        return
    parts = (message.text or "").split(maxsplit=3)
    if len(parts) != 4:
        await message.answer("Формат: /give USER_ID ДНЕЙ VLESS_ССЫЛКА")
        return
    try:
        user_id, days = int(parts[1]), int(parts[2])
        link = parts[3].strip()
        if days not in (30, 90, 180) or not link.startswith(("vless://", "https://")):
            raise ValueError()
        expires = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
        db.execute(
            "INSERT INTO access(user_id, vpn_link, expires_at) VALUES(?,?,?) "
            "ON CONFLICT(user_id) DO UPDATE SET "
            "vpn_link=excluded.vpn_link, expires_at=excluded.expires_at",
            (user_id, link, expires)
        )
        db.execute(
            "UPDATE orders SET status='approved' WHERE user_id=? AND status='pending'",
            (user_id,)
        )
        db.commit()
        await message.bot.send_message(
            user_id,
            f"✅ Доступ выдан на {days} дней!\n\nВаша ссылка:\n"
            f"<code>{html.escape(link)}</code>\n\nДействует до: {expires}",
            parse_mode="HTML"
        )
        await message.answer("Доступ отправлен пользователю.")
    except ValueError:
        await message.answer("Проверьте USER_ID, срок (30/90/180) и ссылку.")
    except Exception:
        logging.exception("Не удалось выдать доступ")
        await message.answer("Не удалось отправить доступ. Проверьте Telegram ID пользователя.")


@dp.message(Command("pending"))
async def pending(message: Message):
    if not is_admin(message.from_user.id):
        return
    rows = db.execute(
        "SELECT id,user_id,plan_days,amount,created_at FROM orders "
        "WHERE status='pending' ORDER BY id DESC LIMIT 20"
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
    if is_admin(message.from_user.id):
        await message.answer(
            "Команды администратора:\n/admin — панель\n"
            "/give USER_ID ДНЕЙ VLESS_ССЫЛКА — выдать VPN\n"
            "/reply USER_ID текст — ответить клиенту\n"
            "/price 30 149 — изменить цену\n"
            "/user USER_ID — карточка клиента\n"
            "/broadcast текст — рассылка"
        )
        return
    if not ADMIN_ID:
        return
    register_user(message.from_user)
    user = message.from_user
    username = f"@{user.username}" if user.username else "нет username"
    header = (
        "📩 <b>Сообщение от покупателя</b>\n"
        f"Имя: {html.escape(user.full_name)}\n"
        f"Username: {html.escape(username)}\n"
        f"Telegram ID: <code>{user.id}</code>\n\n"
        f"Ответить: <code>/reply {user.id} ваш текст</code>"
    )
    await bot.send_message(ADMIN_ID, header, parse_mode="HTML")
    try:
        await message.copy_to(ADMIN_ID)
        await message.answer("✅ Сообщение отправлено администратору. Ожидайте ответа.")
    except Exception:
        logging.exception("Не удалось передать сообщение администратору")
        await message.answer("Не получилось отправить сообщение. Попробуйте ещё раз позже.")


async def main():
    if not BOT_TOKEN or not ADMIN_ID:
        raise RuntimeError("Заполните BOT_TOKEN и ADMIN_ID в переменных окружения.")
    bot = Bot(BOT_TOKEN)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
