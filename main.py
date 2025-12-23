import os
import asyncio
from datetime import datetime, date
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command

TOKEN = os.getenv("BOT_TOKEN")

bot = Bot(token=TOKEN)
dp = Dispatcher()

# Простое хранилище задач: {user_id: [("2025-12-24", "14:30", "текст"), ...]}
user_tasks: dict[int, list[tuple[str, str, str]]] = {}

# Храним имена пользователей и статус "ждём имя"
user_names: dict[int, str] = {}
waiting_for_name: set[int] = set()


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    """Спрашиваем имя пользователя по-китайски."""
    user_id = message.from_user.id
    waiting_for_name.add(user_id)
    await message.answer("你叫什么名字？")


@dp.message(Command("add"))
async def cmd_add(message: types.Message):
    """
    Ожидаем формат:
    /add 14:30 Текст задачи
    """
    user_id = message.from_user.id

    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        await message.answer("Используй формат: /add HH:MM текст задачи\nНапример: /add 09:00 报名汉语课")
        return

    time_str = parts[1]
    task_text = parts[2].strip()

    # Проверяем время
    try:
        datetime.strptime(time_str, "%H:%M")
    except ValueError:
        await message.answer("Неверный формат времени. Используй HH:MM, например 09:30")
        return

    today_str = date.today().isoformat()  # '2025-12-24'

    if user_id not in user_tasks:
        user_tasks[user_id] = []

    user_tasks[user_id].append((today_str, time_str, task_text))

    await message.answer(f"Добавил задачу на сегодня в {time_str}:\n• {task_text}")


@dp.message(Command("today"))
async def cmd_today(message: types.Message):
    user_id = message.from_user.id
    today_str = date.today().isoformat()

    tasks = [
        (t, txt) for d, t, txt in user_tasks.get(user_id, [])
        if d == today_str
    ]

    if not tasks:
        await message.answer("На сегодня задач нет 👌")
        return

    lines = [f"{time} — {text}" for time, text in sorted(tasks)]
    text = "Твои задачи на сегодня:\n\n" + "\n".join(lines)
    await message.answer(text)


@dp.message()  # обработчик всех остальных сообщений
async def handle_name_or_default(message: types.Message):
    """Если ждём имя – запоминаем, иначе игнорируем."""
    user_id = message.from_user.id

    # Если ждём имя и это не команда (не начинается с '/')
    if user_id in waiting_for_name and not message.text.startswith("/"):
        name = message.text.strip()
        user_names[user_id] = name
        waiting_for_name.remove(user_id)

        # Ответ по-китайски: "Сунь Шу теперь точно запомнил твоё имя!"
        await message.answer("孙树已经牢牢记住你的名字了！")
        return

    # Если не ждём имя — тут можно потом добавить общую обработку,
    # сейчас просто ничего не делаем.
    return


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
