import asyncio, os, json, sqlite3, logging
from html import escape
from datetime import datetime

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (Message, CallbackQuery, ReplyKeyboardMarkup,
                           KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton)
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
MANAGER = os.getenv("MANAGER_USERNAME", "your_username")

# ---------- ТЕКСТИ (редагуйте під себе) ----------
WELCOME = ("Добрий день! 👋\nМи допомагаємо студентам з курсовими, дипломними, рефератами, "
           "лабораторними та іншими завданнями.\n\nНатисніть «📝 Замовити роботу» — це займе 2 хвилини.")
ABOUT = ("ℹ️ <b>Про нас</b>\nПрацюємо кілька років, виконуємо роботи у погоджені терміни, "
         "правки безкоштовні.\nнаш ТТ: tiktok.com/@diplomaeasyua")
DISCOUNT = "Приведи друга та отримай 20% знижки на замовлення 🎁"

B_ORDER, B_MY, B_MGR, B_DISC, B_ABOUT = ("📝 Замовити роботу", "📋 Мої замовлення",
    "💬 Зв'язатися з менеджером", "🎓 Моя знижка", "ℹ️ Про нас")

MENU = ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
    [KeyboardButton(text=B_ORDER), KeyboardButton(text=B_MY)],
    [KeyboardButton(text=B_MGR), KeyboardButton(text=B_DISC)],
    [KeyboardButton(text=B_ABOUT)]])

def kb(options, prefix, row=2, skip=False):
    rows, cur = [], []
    for o in options:
        cur.append(InlineKeyboardButton(text=o, callback_data=f"{prefix}:{o}"))
        if len(cur) == row: rows.append(cur); cur = []
    if cur: rows.append(cur)
    if skip: rows.append([InlineKeyboardButton(text="Пропустити", callback_data=f"{prefix}:-")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

# ---------- БАЗА ----------
db = sqlite3.connect("orders.db")
db.execute("""CREATE TABLE IF NOT EXISTS orders(
 id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, username TEXT,
 data TEXT, status TEXT DEFAULT 'Прийнято', created TEXT)""")
db.commit()

# ---------- СТАНИ ----------
class O(StatesGroup):
    uni = State(); spec = State(); year = State(); form = State(); level = State()
    kind = State(); subject = State(); method = State(); sample = State()
    deadline = State(); notes = State(); confirm = State()

r = Router()

# ---------- МЕНЮ ----------
@r.message(CommandStart())
async def start(m: Message, state: FSMContext):
    await state.clear()
    await m.answer(WELCOME, reply_markup=MENU)

@r.message(F.text == B_ABOUT)
async def about(m: Message, state: FSMContext):
    await state.clear(); await m.answer(ABOUT)

@r.message(F.text == B_DISC)
async def disc(m: Message, state: FSMContext):
    await state.clear(); await m.answer(DISCOUNT)

@r.message(F.text == B_MGR)
async def mgr(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("Напишіть менеджеру напряму 👉", reply_markup=InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Відкрити чат", url=f"https://t.me/{MANAGER}")]]))

@r.message(F.text == B_MY)
async def my(m: Message, state: FSMContext):
    await state.clear()
    rows = db.execute("SELECT id,data,status FROM orders WHERE user_id=? ORDER BY id DESC LIMIT 10",
                      (m.from_user.id,)).fetchall()
    if not rows: return await m.answer("У вас ще немає замовлень.")
    txt = "📋 <b>Ваші замовлення:</b>\n\n" + "\n".join(
        f"№{i} — {escape(json.loads(d).get('subject','-'))} — <i>{s}</i>" for i, d, s in rows)
    await m.answer(txt)

# ---------- ЗАМОВЛЕННЯ ----------
@r.message(F.text == B_ORDER)
async def order(m: Message, state: FSMContext):
    await state.clear(); await state.set_state(O.uni)
    await m.answer("🎓 Напишіть назву вашого університету:")

@r.message(O.uni)
async def s_uni(m: Message, state: FSMContext):
    await state.update_data(uni=m.text); await state.set_state(O.spec)
    await m.answer("Яка у вас спеціальність?")

@r.message(O.spec)
async def s_spec(m: Message, state: FSMContext):
    await state.update_data(spec=m.text); await state.set_state(O.year)
    await m.answer("У якому році ви вступили? (наприклад, 2023)")

@r.message(O.year)
async def s_year(m: Message, state: FSMContext):
    await state.update_data(year=m.text); await state.set_state(O.form)
    await m.answer("Форма навчання?", reply_markup=kb(["Денна", "Заочна"], "form"))

@r.callback_query(O.form, F.data.startswith("form:"))
async def s_form(c: CallbackQuery, state: FSMContext):
    await state.update_data(form=c.data.split(":", 1)[1]); await state.set_state(O.level)
    await c.message.answer("Бакалавр чи магістр?", reply_markup=kb(["Бакалавр", "Магістр"], "lvl"))
    await c.answer()

@r.callback_query(O.level, F.data.startswith("lvl:"))
async def s_level(c: CallbackQuery, state: FSMContext):
    await state.update_data(level=c.data.split(":", 1)[1]); await state.set_state(O.kind)
    await c.message.answer("Що саме потрібно?", reply_markup=kb(
        ["Курсова", "Дипломна", "Реферат", "Лабораторна", "Задачі", "Тест онлайн", "Інше"], "kind"))
    await c.answer()

@r.callback_query(O.kind, F.data.startswith("kind:"))
async def s_kind(c: CallbackQuery, state: FSMContext):
    await state.update_data(kind=c.data.split(":", 1)[1]); await state.set_state(O.subject)
    await c.message.answer("Яка дисципліна / тема?")
    await c.answer()

@r.message(O.subject)
async def s_subject(m: Message, state: FSMContext):
    await state.update_data(subject=m.text); await state.set_state(O.method)
    await m.answer("📎 Надішліть методичку з вимогами (файлом) або натисніть «Пропустити».",
                   reply_markup=kb([], "method", skip=True))

@r.message(O.method, F.document)
async def s_method_file(m: Message, state: FSMContext):
    await state.update_data(method_file=m.document.file_id); await to_sample(m, state)

@r.callback_query(O.method, F.data == "method:-")
async def s_method_skip(c: CallbackQuery, state: FSMContext):
    await to_sample(c.message, state); await c.answer()

async def to_sample(m: Message, state: FSMContext):
    await state.set_state(O.sample)
    await m.answer("📄 Є зразок подібної роботи? Надішліть файл або натисніть «Пропустити».",
                   reply_markup=kb([], "sample", skip=True))

@r.message(O.sample, F.document)
async def s_sample_file(m: Message, state: FSMContext):
    await state.update_data(sample_file=m.document.file_id); await to_deadline(m, state)

@r.callback_query(O.sample, F.data == "sample:-")
async def s_sample_skip(c: CallbackQuery, state: FSMContext):
    await to_deadline(c.message, state); await c.answer()

async def to_deadline(m: Message, state: FSMContext):
    await state.set_state(O.deadline)
    await m.answer("📅 До якої дати потрібна робота? (напишіть дату або «не важливо»)")

@r.message(O.deadline)
async def s_deadline(m: Message, state: FSMContext):
    await state.update_data(deadline=m.text); await state.set_state(O.notes)
    await m.answer("Додаткові вимоги чи побажання? Якщо немає — натисніть «Пропустити».",
                   reply_markup=kb([], "notes", skip=True))

async def show_confirm(m: Message, state: FSMContext):
    d = await state.get_data(); await state.set_state(O.confirm)
    txt = ("Перевірте, чи все вірно:\n"
           f"🏫 {escape(d['uni'])}\n🎓 {escape(d['spec'])}, вступ {escape(d['year'])} "
           f"({d['form']}, {d['level']})\n📌 {d['kind']}: {escape(d['subject'])}\n"
           f"📅 {escape(d['deadline'])}\n📝 {escape(d.get('notes') or '—')}")
    await m.answer(txt, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Все вірно", callback_data="ok"),
        InlineKeyboardButton(text="❌ Скасувати", callback_data="cancel")]]))

@r.message(O.notes)
async def s_notes(m: Message, state: FSMContext):
    await state.update_data(notes=m.text); await show_confirm(m, state)

@r.callback_query(O.notes, F.data == "notes:-")
async def s_notes_skip(c: CallbackQuery, state: FSMContext):
    await show_confirm(c.message, state); await c.answer()

@r.callback_query(O.confirm, F.data == "cancel")
async def cancel(c: CallbackQuery, state: FSMContext):
    await state.clear(); await c.message.answer("Замовлення скасовано.", reply_markup=MENU); await c.answer()

@r.callback_query(O.confirm, F.data == "ok")
async def done(c: CallbackQuery, state: FSMContext, bot: Bot):
    d = await state.get_data(); await state.clear()
    cur = db.execute("INSERT INTO orders(user_id,username,data,created) VALUES(?,?,?,?)",
        (c.from_user.id, c.from_user.username, json.dumps(d, ensure_ascii=False),
         datetime.now().strftime("%d.%m.%Y %H:%M")))
    db.commit(); num = cur.lastrowid
    await c.message.answer(f"Дякуємо! Замовлення №{num} прийнято 🙌 Скоро зв'яжемось із вами.", reply_markup=MENU)
    who = f'<a href="tg://user?id={c.from_user.id}">{escape(c.from_user.full_name)}</a>'
    un = f" (@{c.from_user.username})" if c.from_user.username else ""
    await bot.send_message(ADMIN_ID,
        f"🆕 <b>Замовлення №{num}</b>\n👤 {who}{un}\n🏫 {escape(d['uni'])}\n"
        f"🎓 {escape(d['spec'])}, {escape(d['year'])}, {d['form']}, {d['level']}\n"
        f"📌 {d['kind']}: {escape(d['subject'])}\n📅 {escape(d['deadline'])}\n"
        f"📝 {escape(d.get('notes') or '—')}")
    for key in ("method_file", "sample_file"):
        if d.get(key): await bot.send_document(ADMIN_ID, d[key], caption=f"№{num}: {key}")
    await c.answer()

async def main():
    logging.basicConfig(level=logging.INFO)
    bot = Bot(TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage()); dp.include_router(r)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
