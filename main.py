import os
from dotenv import load_dotenv
load_dotenv()
import asyncio
from datetime import datetime, date
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from database import init_db, SessionLocal, add_task, get_tasks_for_date, upsert_daily_log, get_daily_log

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("BOT_TOKEN is not set. Проверь .env или Railway variables.")


bot = Bot(token=TOKEN)
dp = Dispatcher()

# user_tasks больше не нужен — все в БД
# user_tasks: dict[int, list[tuple[str, str, str]]] = {}



@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    text = (
        "Привет! Я бот-планировщик.\n\n"
        "Команды:\n"
        "пример: /add 14:30 Позвонить маме\n"
        "/today — показать задачи на сегодня\n"
    )
    await message.answer(text)


@dp.message(Command("add"))
async def cmd_add(message: types.Message):
    """
    Ожидаем формат:
    /add 14:30 Текст задачи
    """
    user_id = message.from_user.id

    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        await message.answer("Используй формат: /add HH:MM текст задачи\nНапример: /add 09:00 Пойти на тренировку")
        return

    time_str = parts[1]
    task_text = parts[2].strip()

    # Проверяем время
    try:
        datetime.strptime(time_str, "%H:%M")
    except ValueError:
        await message.answer("Неверный формат времени. Используй HH:MM, например 09:30")
        return

    today_obj = date.today()

    db = SessionLocal()
    try:
        # category можно пока не использовать (оставляем None)
        add_task(db, tg_id=user_id, date_obj=today_obj, time_str=time_str, text=task_text)
    finally:
        db.close()

    await message.answer(f"Добавил задачу на сегодня в {time_str}:\n• {task_text}")



@dp.message(Command("today"))
async def cmd_today(message: types.Message):
    user_id = message.from_user.id
    today_obj = date.today()

    db = SessionLocal()
    try:
        tasks = get_tasks_for_date(db, tg_id=user_id, date_obj=today_obj)
    finally:
        db.close()

    if not tasks:
        await message.answer("На сегодня задач нет 👌")
        return

    lines = [f"{task.start_time} — {task.text}" for task in tasks]
    text = "Твои задачи на сегодня:\n\n" + "\n".join(lines)
    await message.answer(text)



@dp.message(Command("mood"))
async def cmd_mood(message: types.Message):
    """
    Пример формата:
    /mood calm 7.5 clear 8 3
    (mood, sleep_hours, focus_level, energy, stress)

    Можно начать с очень простых значений для себя.
    """
    user_id = message.from_user.id

    parts = message.text.split()
    if len(parts) < 6:
        await message.answer(
            "Формат: /mood mood sleep_hours focus_level energy stress\n"
            "Например: /mood calm 7.5 clear 8 3"
        )
        return

    mood = parts[1]
    try:
        sleep_hours = float(parts[2])
    except ValueError:
        await message.answer("sleep_hours должно быть числом, например 7.5")
        return

    focus_level = parts[3]

    try:
        energy = int(parts[4])
        stress = int(parts[5])
    except ValueError:
        await message.answer("energy и stress должны быть целыми числами, например 8 3")
        return

    today_obj = date.today()

    db = SessionLocal()
    try:
        upsert_daily_log(
            db,
            tg_id=user_id,
            date_obj=today_obj,
            mood=mood,
            sleep_hours=sleep_hours,
            focus_level=focus_level,
            energy=energy,
            stress=stress,
        )
    finally:
        db.close()

    await message.answer("Записал твоё состояние на сегодня 👍")



@dp.message(Command("mood_today"))
async def cmd_mood_today(message: types.Message):
    user_id = message.from_user.id
    today_obj = date.today()

    db = SessionLocal()
    try:
        log = get_daily_log(db, tg_id=user_id, date_obj=today_obj)
    finally:
        db.close()

    if not log:
        await message.answer("На сегодня ещё нет записи настроения.")
        return

    text = (
        f"Сегодняшнее состояние:\n"
        f"- Настроение: {log.mood}\n"
        f"- Сон: {log.sleep_hours} ч\n"
        f"- Фокус: {log.focus_level}\n"
        f"- Энергия: {log.energy}/10\n"
        f"- Стресс: {log.stress}/10\n"
    )
    await message.answer(text)



async def main():
    init_db()  # <-- ВАЖНО: создаём таблицы
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

