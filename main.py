# main.py
import os
import asyncio
from datetime import datetime, date
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command

from database import (
    init_db,
    SessionLocal,
    add_task,
    get_tasks_for_date,
    set_task_done,
    set_availability,
    add_busy,
    generate_plan,
    get_plan,
)

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")

bot = Bot(token=TOKEN)
dp = Dispatcher()

HELP_TEXT = (
    "Команды (простые):\n\n"
    "• /add 14:30 Текст — добавить задачу на сегодня (в 14:30)\n"
    "• /add Текст — добавить задачу без времени (бот сам поставит в план)\n"
    "• /today — список задач на сегодня (с ID)\n"
    "• /done <id> — отметить выполненной\n"
    "• /undo <id> — вернуть в невыполненные\n\n"
    "Время (чтобы план был реальным):\n"
    "• /availability 18:00-22:00 — когда ты свободен сегодня\n"
    "• /busy 19:00-19:30 — когда ты занят сегодня\n\n"
    "План:\n"
    "• /plan_generate — построить план на сегодня\n"
    "• /plan_show — показать сохранённый план\n"
)


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("Привет! Я бот-планировщик.\n\n" + HELP_TEXT)


@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer(HELP_TEXT)


@dp.message(Command("add"))
async def cmd_add(message: types.Message):
    """
    /add 14:30 текст
    /add текст
    """
    user_id = message.from_user.id
    raw = message.text.strip()

    parts = raw.split(maxsplit=2)
    if len(parts) < 2:
        await message.answer("Формат: /add 14:30 текст\nили просто: /add текст")
        return

    time_str = None
    text = None

    # если второй токен похож на HH:MM
    if len(parts) >= 3:
        maybe_time = parts[1]
        try:
            datetime.strptime(maybe_time, "%H:%M")
            time_str = maybe_time
            text = parts[2].strip()
        except ValueError:
            # значит времени нет
            text = raw[len("/add"):].strip()
    else:
        text = raw[len("/add"):].strip()

    if not text:
        await message.answer("Напиши текст задачи после /add")
        return

    with SessionLocal() as db:
        add_task(db, tg_id=user_id, date_obj=date.today(), time_str=time_str, text=text, minutes=30)

    if time_str:
        await message.answer(f"Добавил: {time_str} — {text}")
    else:
        await message.answer(f"Добавил без времени: {text}\n(бот поставит её сам при /plan_generate)")


@dp.message(Command("today"))
async def cmd_today(message: types.Message):
    user_id = message.from_user.id
    today = date.today()

    with SessionLocal() as db:
        tasks = get_tasks_for_date(db, tg_id=user_id, date_obj=today)

    if not tasks:
        await message.answer("На сегодня задач нет.")
        return

    lines = []
    for t in tasks:
        status = "✅" if t.done else "⬜️"
        when = t.start_time if t.start_time else "--:--"
        lines.append(f"{status} [{t.id}] {when} — {t.text}")

    await message.answer("Задачи на сегодня:\n" + "\n".join(lines))


@dp.message(Command("done"))
async def cmd_done(message: types.Message):
    user_id = message.from_user.id
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Формат: /done <id>")
        return
    task_id = int(parts[1])

    with SessionLocal() as db:
        ok = set_task_done(db, tg_id=user_id, task_id=task_id, done=True)

    await message.answer("Готово ✅" if ok else "Не нашёл задачу с таким ID.")


@dp.message(Command("undo"))
async def cmd_undo(message: types.Message):
    user_id = message.from_user.id
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Формат: /undo <id>")
        return
    task_id = int(parts[1])

    with SessionLocal() as db:
        ok = set_task_done(db, tg_id=user_id, task_id=task_id, done=False)

    await message.answer("Вернул в невыполненные ⬜️" if ok else "Не нашёл задачу с таким ID.")


@dp.message(Command("availability"))
async def cmd_availability(message: types.Message):
    user_id = message.from_user.id
    parts = message.text.split(maxsplit=1)
    if len(parts) != 2 or "-" not in parts[1]:
        await message.answer("Формат: /availability 18:00-22:00")
        return

    start, end = parts[1].split("-", 1)
    start = start.strip()
    end = end.strip()

    try:
        datetime.strptime(start, "%H:%M")
        datetime.strptime(end, "%H:%M")
    except ValueError:
        await message.answer("Время должно быть в формате HH:MM, например 18:00-22:00")
        return

    with SessionLocal() as db:
        set_availability(db, tg_id=user_id, date_obj=date.today(), start_hhmm=start, end_hhmm=end)

    await message.answer(f"Ок. Свободное время сегодня: {start}-{end}")


@dp.message(Command("busy"))
async def cmd_busy(message: types.Message):
    user_id = message.from_user.id
    parts = message.text.split(maxsplit=1)
    if len(parts) != 2 or "-" not in parts[1]:
        await message.answer("Формат: /busy 19:00-19:30")
        return

    start, end = parts[1].split("-", 1)
    start = start.strip()
    end = end.strip()

    try:
        datetime.strptime(start, "%H:%M")
        datetime.strptime(end, "%H:%M")
    except ValueError:
        await message.answer("Время должно быть в формате HH:MM, например 19:00-19:30")
        return

    with SessionLocal() as db:
        add_busy(db, tg_id=user_id, date_obj=date.today(), start_hhmm=start, end_hhmm=end)

    await message.answer(f"Добавил занятое время: {start}-{end}")


@dp.message(Command("plan_generate"))
async def cmd_plan_generate(message: types.Message):
    user_id = message.from_user.id
    today = date.today()

    with SessionLocal() as db:
        plan_id, not_scheduled = generate_plan(db, tg_id=user_id, date_obj=today)

    if not_scheduled:
        await message.answer(
            f"План построен (ID плана: {plan_id}).\n"
            f"Не влезли задачи (по ID): {', '.join(map(str, not_scheduled))}\n"
            f"Посмотреть план: /plan_show"
        )
    else:
        await message.answer(f"План построен (ID плана: {plan_id}).\nПосмотреть: /plan_show")


@dp.message(Command("plan_show"))
async def cmd_plan_show(message: types.Message):
    user_id = message.from_user.id
    today = date.today()

    with SessionLocal() as db:
        res = get_plan(db, tg_id=user_id, date_obj=today)

    if not res:
        await message.answer("Плана на сегодня нет. Сделай: /plan_generate")
        return

    _, items = res
    if not items:
        await message.answer("План пустой (возможно нет задач).")
        return

    lines = [f"{s}-{e} — [{task_id}] {text}" for (s, e, task_id, text) in items]
    await message.answer("План на сегодня:\n" + "\n".join(lines))


async def main():
    init_db()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
