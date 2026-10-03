import asyncio, os, json, sqlite3, logging
from html import escape
from datetime import datetime

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (Message, CallbackQuery, ReplyKeyboardMarkup,
                           KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton)
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
MANAGER = os.getenv("MANAGER_USERNAME", "Tehexpert0").lstrip("@")

# =====================  НАЛАШТУВАННЯ (редагуйте під себе)  =====================
REPLY_MINUTES = 15            # у скільки хвилин реально відповідаєте (пишіть ЛИШЕ правду)
WORK_HOURS = "щодня 9:00–22:00"
REMIND_AFTER_MIN = 20         # нагадати, якщо людина кинула заявку на пів дорозі
TIKTOK = "tiktok.com/@diplomaeasyua"

# Орієнтовні ціни "від". Залиште порожнім {}, якщо не хочете показувати ціни.
# Приклад: {"Курсова": 800, "Реферат": 250}
PRICE_FROM = {}

# Додавайте тільки те, що правда. Вигадані цифри/відгуки б'ють по репутації.
ABOUT = ("ℹ️ <b>Чому нам довіряють</b>\n\n"
         "✅ Працюємо кілька років\n"
         "✅ Дотримуємось погоджених термінів\n"
         "✅ Правки безкоштовні\n"
         "✅ Вартість рахуємо безкоштовно, без зобов'язань\n\n"
         f"Наш TikTok: {TIKTOK}")
# ===============================================================================

KINDS = ["Курсова", "Дипломна", "Реферат", "Лабораторна", "Задачі", "Тест онлайн", "Інше"]
KIND_ICONS = {"Курсова": "📘", "Дипломна": "🎓", "Реферат": "📄", "Лабораторна": "🔬",
              "Задачі": "🧮", "Тест онлайн": "💻", "Інше": "✨"}
DEADLINES = ["🔥 1–3 дні", "📆 До тижня", "🗓 1–2 тижні", "🌿 Місяць і більше", "🤷 Ще не знаю"]
STEPS = 5

B_ORDER, B_MY, B_MGR, B_DISC, B_ABOUT = ("📝 Замовити роботу", "📋 Мої замовлення",
    "💬 Менеджер", "🎁 Знижка за друга", "ℹ️ Чому ми")

MENU = ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
    [KeyboardButton(text=B_ORDER)],
    [KeyboardButton(text=B_MY), KeyboardButton(text=B_MGR)],
    [KeyboardButton(text=B_DISC), KeyboardButton(text=B_ABOUT)]])

STATUS_TEXT = {
    "Оцінено": "💰 Ми оцінили замовлення №{n}. Менеджер надішле вартість і терміни.",
    "В роботі": "🛠 Замовлення №{n} взято в роботу.",
    "Готово": "🎉 Замовлення №{n} готове! Менеджер передасть його вам.",
}
STATUS_ICON = {"Прийнято": "🕐", "Оцінено": "💰", "В роботі": "🛠", "Готово": "✅"}


def kb(options, prefix, row=2, skip=False, icons=None):
    rows, cur = [], []
    for i, o in enumerate(options):
        label = f"{icons.get(o, '')} {o}".strip() if icons else o
        cur.append(InlineKeyboardButton(text=label, callback_data=f"{prefix}:{i}"))
        if len(cur) == row:
            rows.append(cur); cur = []
    if cur: rows.append(cur)
    if skip: rows.append([InlineKeyboardButton(text="Пропустити ➡️", callback_data=f"{prefix}:-")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def manager_btn(text="💬 Написати менеджеру"):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=text, url=f"https://t.me/{MANAGER}")]])


def step(n): return f"<i>Крок {n} з {STEPS}</i>\n"


# ---------- БАЗА ----------
db = sqlite3.connect("orders.db")
db.execute("""CREATE TABLE IF NOT EXISTS orders(
 id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, username TEXT,
 data TEXT, status TEXT DEFAULT 'Прийнято', created TEXT)""")
db.execute("""CREATE TABLE IF NOT EXISTS users(
 user_id INTEGER PRIMARY KEY, referrer INTEGER, joined TEXT)""")
db.commit()


def register_user(uid, referrer=None):
    if db.execute("SELECT 1 FROM users WHERE user_id=?", (uid,)).fetchone():
        return
    if referrer == uid: referrer = None
    db.execute("INSERT INTO users(user_id,referrer,joined) VALUES(?,?,?)",
               (uid, referrer, datetime.now().strftime("%d.%m.%Y %H:%M")))
    db.commit()


# ---------- СТАНИ ----------
class O(StatesGroup):
    kind = State(); subject = State(); deadline = State()
    files = State(); details = State(); confirm = State()


r = Router()
_tasks = set()


async def pick(c: CallbackQuery, label: str):
    """Показує, що саме обрала людина, і прибирає кнопки (щоб не тиснули двічі)."""
    try:
        await c.message.edit_text(f"{c.message.html_text}\n\n✔ <b>{escape(label)}</b>", reply_markup=None)
    except Exception:
        pass


# ---------- МЕНЮ ----------
WELCOME = ("Привіт{name}! 👋\n\n"
           "Допомагаємо зі студентськими роботами: курсові, дипломні, реферати, лабораторні, задачі.\n\n"
           f"⚡ Відповідаємо протягом ~{REPLY_MINUTES} хв ({WORK_HOURS})\n"
           "🆓 Вартість і терміни рахуємо безкоштовно та без зобов'язань\n\n"
           "Натисніть «📝 Замовити роботу» — це 5 коротких питань, ~1 хвилина.")


@r.message(CommandStart(deep_link=True))
async def start_ref(m: Message, command: CommandObject, state: FSMContext):
    ref = None
    if command.args and command.args.startswith("ref_") and command.args[4:].isdigit():
        ref = int(command.args[4:])
    register_user(m.from_user.id, ref)
    await start(m, state)


@r.message(CommandStart())
async def start(m: Message, state: FSMContext):
    await state.clear()
    register_user(m.from_user.id)
    name = f", {escape(m.from_user.first_name)}" if m.from_user.first_name else ""
    await m.answer(WELCOME.format(name=name), reply_markup=MENU)


@r.message(Command("cancel"))
async def cancel_cmd(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("Скасовано. Повернутися до заявки можна будь-коли 🙂", reply_markup=MENU)


@r.message(F.text == B_ABOUT)
async def about(m: Message, state: FSMContext):
    await state.clear(); await m.answer(ABOUT, reply_markup=manager_btn("💬 Поставити питання"))


@r.message(F.text == B_DISC)
async def disc(m: Message, state: FSMContext):
    await state.clear()
    me = await m.bot.me()
    link = f"https://t.me/{me.username}?start=ref_{m.from_user.id}"
    friends = db.execute("SELECT COUNT(*) FROM users WHERE referrer=?", (m.from_user.id,)).fetchone()[0]
    await m.answer(
        "🎁 <b>Знижка 20% — вам і другу</b>\n\n"
        "Надішліть другу своє посилання. Коли він зробить замовлення — "
        "ви обоє отримаєте 20% знижки.\n\n"
        f"🔗 Ваше посилання:\n{link}\n\n"
        f"Друзів, що прийшли за посиланням: <b>{friends}</b>")


@r.message(F.text == B_MGR)
async def mgr(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("Напишіть менеджеру напряму — відповідаємо швидко 👇", reply_markup=manager_btn("Відкрити чат"))


@r.message(F.text == B_MY)
async def my(m: Message, state: FSMContext):
    await state.clear()
    rows = db.execute("SELECT id,data,status,created FROM orders WHERE user_id=? ORDER BY id DESC LIMIT 10",
                      (m.from_user.id,)).fetchall()
    if not rows:
        return await m.answer("Замовлень поки немає. Розрахунок вартості — безкоштовний 😉",
                              reply_markup=MENU)
    lines = []
    for i, d, s, created in rows:
        d = json.loads(d)
        title = escape(f"{d.get('kind', '')}: {d.get('subject', '-')}"[:45])
        lines.append(f"№{i} · {title}\n{STATUS_ICON.get(s, '•')} <i>{escape(s)}</i> · {created}")
    await m.answer("📋 <b>Ваші замовлення</b>\n\n" + "\n\n".join(lines))


# ---------- ЗАМОВЛЕННЯ ----------
async def remind(bot: Bot, chat_id: int, state: FSMContext, flow: str):
    await asyncio.sleep(REMIND_AFTER_MIN * 60)
    try:
        st = await state.get_state()
        if st and st.startswith("O:") and (await state.get_data()).get("flow") == flow:
            await bot.send_message(chat_id, "Ваша заявка майже готова 🙂 Вона збережена — просто "
                                            "дайте відповідь на останнє питання вище.\n"
                                            "Або напишіть менеджеру, якщо щось незрозуміло.",
                                   reply_markup=manager_btn())
    except Exception:
        pass


@r.message(F.text == B_ORDER)
async def order(m: Message, state: FSMContext):
    await state.clear()
    flow = str(m.message_id)
    await state.set_state(O.kind)
    await state.update_data(flow=flow, files=[])
    await m.answer("Чудово, почнемо! Це швидко, а розрахунок безкоштовний 👌\n\n"
                   + step(1) + "<b>Що потрібно зробити?</b>",
                   reply_markup=kb(KINDS, "kind", icons=KIND_ICONS))
    t = asyncio.create_task(remind(m.bot, m.chat.id, state, flow))
    _tasks.add(t); t.add_done_callback(_tasks.discard)


@r.callback_query(O.kind, F.data.startswith("kind:"))
async def s_kind(c: CallbackQuery, state: FSMContext):
    kind = KINDS[int(c.data.split(":")[1])]
    await state.update_data(kind=kind); await state.set_state(O.subject)
    await pick(c, kind)
    await c.message.answer(step(2) + "<b>З якого предмета і на яку тему?</b>\n"
                                     "Можна коротко, наприклад: «Маркетинг, тема — digital-стратегія кав'ярні»")
    await c.answer()


@r.message(O.subject, F.text)
async def s_subject(m: Message, state: FSMContext):
    await state.update_data(subject=m.text[:300]); await state.set_state(O.deadline)
    await m.answer(step(3) + "<b>Коли потрібна робота?</b>\nОберіть варіант або напишіть свою дату.",
                   reply_markup=kb(DEADLINES, "dl", row=2))


async def to_files(m: Message, state: FSMContext):
    await state.set_state(O.files)
    await m.answer(step(4) + "<b>Є методичка, вимоги чи зразок?</b>\n"
                             "Надішліть файли або фото (можна кілька) — так менеджер порахує точніше.",
                   reply_markup=kb([], "files", skip=True))


@r.callback_query(O.deadline, F.data.startswith("dl:"))
async def s_deadline_btn(c: CallbackQuery, state: FSMContext):
    idx = int(c.data.split(":")[1])
    await state.update_data(deadline=DEADLINES[idx], urgent=(idx == 0))
    await pick(c, DEADLINES[idx])
    await to_files(c.message, state); await c.answer()


@r.message(O.deadline, F.text)
async def s_deadline_txt(m: Message, state: FSMContext):
    await state.update_data(deadline=m.text[:100], urgent=False)
    await to_files(m, state)


async def to_details(m: Message, state: FSMContext):
    await state.set_state(O.details)
    await m.answer(step(5) + "<b>Останнє!</b> Напишіть одним повідомленням: університет, спеціальність "
                             "і будь-які побажання. Це необов'язково — можна пропустити.",
                   reply_markup=kb([], "details", skip=True))


@r.message(O.files, F.document | F.photo)
async def s_file(m: Message, state: FSMContext):
    d = await state.get_data()
    files = d.get("files", [])
    if len(files) >= 10:
        return await m.answer("Максимум 10 файлів. Решту можна надіслати менеджеру 👌")
    files.append(["document", m.document.file_id] if m.document else ["photo", m.photo[-1].file_id])
    await state.update_data(files=files)
    await m.answer(f"Отримали ✅ Файлів: {len(files)}. Можна додати ще або йти далі.",
                   reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                       InlineKeyboardButton(text="✅ Готово, далі", callback_data="files:-")]]))


@r.callback_query(O.files, F.data == "files:-")
async def s_files_done(c: CallbackQuery, state: FSMContext):
    await pick(c, "Далі")
    await to_details(c.message, state); await c.answer()


@r.message(O.files)
async def files_fallback(m: Message):
    await m.answer("Надішліть файл/фото або натисніть «Пропустити» ☝️")


async def show_confirm(m: Message, state: FSMContext):
    d = await state.get_data(); await state.set_state(O.confirm)
    price = PRICE_FROM.get(d["kind"])
    txt = ("<b>Перевірте заявку:</b>\n\n"
           f"📌 {escape(d['kind'])}: {escape(d['subject'])}\n"
           f"📅 {escape(d['deadline'])}\n"
           f"📎 Файлів: {len(d.get('files', []))}\n"
           f"📝 {escape(d.get('details') or '—')}")
    if price:
        txt += f"\n\n💰 Орієнтовно від {price} грн — точну ціну назве менеджер."
    txt += "\n\nЦе ще не оплата — ми лише порахуємо вартість і напишемо вам."
    await m.answer(txt, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Надіслати на розрахунок", callback_data="ok")],
        [InlineKeyboardButton(text="🔄 Заповнити заново", callback_data="redo")]]))


@r.message(O.details, F.text)
async def s_details(m: Message, state: FSMContext):
    await state.update_data(details=m.text[:600]); await show_confirm(m, state)


@r.callback_query(O.details, F.data == "details:-")
async def s_details_skip(c: CallbackQuery, state: FSMContext):
    await pick(c, "Пропущено")
    await show_confirm(c.message, state); await c.answer()


@r.callback_query(O.confirm, F.data == "redo")
async def redo(c: CallbackQuery, state: FSMContext):
    await state.clear(); await c.message.edit_reply_markup(reply_markup=None)
    await c.message.answer("Без проблем! Натисніть «📝 Замовити роботу», щоб почати заново.", reply_markup=MENU)
    await c.answer()


@r.callback_query(O.confirm, F.data == "ok")
async def done(c: CallbackQuery, state: FSMContext, bot: Bot):
    d = await state.get_data(); await state.clear()
    await c.message.edit_reply_markup(reply_markup=None)
    data = {k: d.get(k) for k in ("kind", "subject", "deadline", "details", "files", "urgent")}
    cur = db.execute("INSERT INTO orders(user_id,username,data,created) VALUES(?,?,?,?)",
                     (c.from_user.id, c.from_user.username, json.dumps(data, ensure_ascii=False),
                      datetime.now().strftime("%d.%m.%Y %H:%M")))
    db.commit(); num = cur.lastrowid

    await c.message.answer(
        f"🙌 Дякуємо! Заявку №{num} прийнято.\n\n"
        f"Менеджер напише вам у Telegram приблизно за {REPLY_MINUTES} хв ({WORK_HOURS}) "
        "з вартістю і термінами. Вирішите після розрахунку — без зобов'язань.\n\n"
        "Статус можна дивитися в «📋 Мої замовлення».", reply_markup=MENU)
    await c.message.answer("Якщо є що додати — напишіть менеджеру прямо зараз 👇", reply_markup=manager_btn())

    ref = db.execute("SELECT referrer FROM users WHERE user_id=?", (c.from_user.id,)).fetchone()
    first = db.execute("SELECT COUNT(*) FROM orders WHERE user_id=?", (c.from_user.id,)).fetchone()[0] == 1
    who = f'<a href="tg://user?id={c.from_user.id}">{escape(c.from_user.full_name)}</a>'
    un = f" (@{c.from_user.username})" if c.from_user.username else ""
    flags = ("🔥 <b>ТЕРМІНОВО</b>\n" if d.get("urgent") else "")
    if ref and ref[0] and first:
        flags += f"🎁 Прийшов від друга (id {ref[0]}) — знижка 20% обом\n"
    try:
        await bot.send_message(ADMIN_ID,
            f"🆕 <b>Замовлення №{num}</b>\n{flags}👤 {who}{un}\n"
            f"📌 {escape(d['kind'])}: {escape(d['subject'])}\n📅 {escape(d['deadline'])}\n"
            f"📝 {escape(d.get('details') or '—')}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="💰 Оцінено", callback_data=f"st:{num}:Оцінено"),
                InlineKeyboardButton(text="🛠 В роботі", callback_data=f"st:{num}:В роботі"),
                InlineKeyboardButton(text="✅ Готово", callback_data=f"st:{num}:Готово")]]))
        for ftype, fid in d.get("files", []):
            if ftype == "photo": await bot.send_photo(ADMIN_ID, fid, caption=f"№{num}")
            else: await bot.send_document(ADMIN_ID, fid, caption=f"№{num}")
    except Exception:
        logging.exception("Не вдалося надіслати замовлення адміну")
    await c.answer()


# ---------- АДМІН: зміна статусу (клієнт отримує сповіщення) ----------
@r.callback_query(F.data.startswith("st:"))
async def set_status(c: CallbackQuery, bot: Bot):
    if c.from_user.id != ADMIN_ID:
        return await c.answer()
    _, n, st = c.data.split(":", 2)
    row = db.execute("SELECT user_id FROM orders WHERE id=?", (n,)).fetchone()
    if not row or st not in STATUS_TEXT:
        return await c.answer("Не знайдено")
    db.execute("UPDATE orders SET status=? WHERE id=?", (st, n)); db.commit()
    try:
        await bot.send_message(row[0], STATUS_TEXT[st].format(n=n))
    except Exception:
        pass
    await c.answer(f"№{n} → {st}")


# ---------- ЗАПОБІЖНИКИ ----------
@r.message(StateFilter(O.kind, O.confirm))
async def need_button(m: Message):
    await m.answer("Оберіть, будь ласка, варіант кнопкою вище ☝️")


@r.message(StateFilter(O.subject, O.deadline, O.details))
async def need_text(m: Message):
    await m.answer("Тут потрібна текстова відповідь 🙂 Напишіть її повідомленням.")


@r.message(StateFilter(None))
async def fallback(m: Message):
    await m.answer("Оберіть дію в меню нижче або напишіть менеджеру 👇", reply_markup=MENU)


async def main():
    logging.basicConfig(level=logging.INFO)
    if not TOKEN: raise SystemExit("Не задано BOT_TOKEN у .env")
    bot = Bot(TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage()); dp.include_router(r)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())