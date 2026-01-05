# main.py
import os
import asyncio
from datetime import datetime, date, timedelta

from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command

from database import (
    init_db,
    SessionLocal,
    add_task,
    list_tasks_for_date,
    list_tasks_week,
    search_tasks,
    set_task_done,
    delete_task,
    move_task,
    edit_task,
    upsert_daily_log,
    get_daily_log,
    add_repeat,
    list_repeats,
    delete_repeat,
    ensure_repeats_generated,
    set_availability,
    add_busy,
    get_availability_and_busy,
    generate_plan,
    get_plan_items,
    lock_plan,
)

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")

bot = Bot(token=TOKEN)
dp = Dispatcher()


def parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def valid_time(s: str) -> bool:
    try:
        datetime.strptime(s, "%H:%M")
        return True
    except ValueError:
        return False


def parse_kv_args(tokens: list[str]) -> tuple[dict[str, str], str]:
    """
    Разбирает параметры вида p=high m=45 due=2026-01-10 cat=study diff=hard
    Возвращает (params, rest_text)
    """
    params: dict[str, str] = {}
    rest = []
    for t in tokens:
        if "=" in t:
            k, v = t.split("=", 1)
            params[k.strip().lower()] = v.strip()
        else:
            rest.append(t)
    return params, " ".join(rest).strip()


def task_line(t) -> str:
    status = "✅" if t.done else "⬜"
    cat = f" #{t.category}" if t.category else ""
    meta = []
    if t.priority:
        meta.append(f"p={t.priority}")
    if t.estimated_minutes:
        meta.append(f"m={t.estimated_minutes}")
    if t.due_date:
        meta.append(f"due={t.due_date.isoformat()}")
    if t.difficulty:
        meta.append(f"diff={t.difficulty}")
    meta_txt = f" ({', '.join(meta)})" if meta else ""
    return f"{status} [{t.id}] {t.start_time} — {t.text}{cat}{meta_txt}"


@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    await message.answer(
        "Команды:\n"
        "/add HH:MM p=high m=45 due=YYYY-MM-DD cat=study diff=hard текст\n"
        "/today [all|todo|done] [cat=NAME]\n"
        "/week\n"
        "/date YYYY-MM-DD\n"
        "/search слово\n\n"
        "Управление:\n"
        "/done ID | /undo ID | /delete ID\n"
        "/move ID YYYY-MM-DD | /move ID tomorrow\n"
        "/edit ID HH:MM p=... m=... due=... cat=... diff=... текст\n\n"
        "Повторы:\n"
        "/repeat add daily HH:MM текст\n"
        "/repeat add weekdays HH:MM текст\n"
        "/repeat add weekly mon|tue|wed|thu|fri|sat|sun HH:MM текст\n"
        "/repeat list\n"
        "/repeat delete ID\n\n"
        "Время:\n"
        "/availability HH:MM-HH:MM (на сегодня)\n"
        "/busy HH:MM-HH:MM (на сегодня)\n\n"
        "План:\n"
        "/plan generate | /plan show | /plan regenerate | /plan lock\n\n"
        "Состояние:\n"
        "/mood mood sleep focus energy stress\n"
        "пример: /mood calm 7.5 clear 8 3\n"
        "/mood_today"
    )


@dp.message(Command("add"))
async def add_cmd(message: types.Message):
    parts = message.text.split()
    if len(parts) < 3:
        await message.answer("Формат: /add HH:MM [p=high] [m=45] [due=YYYY-MM-DD] [cat=study] [diff=hard] текст")
        return

    time_str = parts[1]
    if not valid_time(time_str):
        await message.answer("Время должно быть HH:MM")
        return

    params, text = parse_kv_args(parts[2:])
    if not text:
        await message.answer("Нет текста задачи.")
        return

    p = params.get("p")
    m = int(params["m"]) if "m" in params and params["m"].isdigit() else None
    cat = params.get("cat")
    diff = params.get("diff")
    due = parse_date(params["due"]) if "due" in params else None

    with SessionLocal() as db:
        ensure_repeats_generated(db, message.from_user.id, date.today())
        task_id = add_task(
            db,
            tg_id=message.from_user.id,
            date_obj=date.today(),
            time_str=time_str,
            text=text,
            category=cat,
            priority=p,
            estimated_minutes=m,
            due_date=due,
            difficulty=diff,
        )

    await message.answer(f"Добавил: ID={task_id}")


@dp.message(Command("today"))
async def today_cmd(message: types.Message):
    tokens = message.text.split()[1:]
    show = "all"
    cat = None

    for t in tokens:
        tl = t.lower()
        if tl in ("all", "todo", "done"):
            show = tl
        if tl.startswith("cat="):
            cat = t.split("=", 1)[1].strip()

    with SessionLocal() as db:
        ensure_repeats_generated(db, message.from_user.id, date.today())
        tasks = list_tasks_for_date(db, message.from_user.id, date.today(), show=show, category=cat)

    if not tasks:
        await message.answer("Пусто.")
        return

    await message.answer("Сегодня:\n" + "\n".join(task_line(t) for t in tasks))


@dp.message(Command("week"))
async def week_cmd(message: types.Message):
    start = date.today()
    with SessionLocal() as db:
        # сгенерим повторы на каждый день недели
        for i in range(7):
            ensure_repeats_generated(db, message.from_user.id, start + timedelta(days=i))
        tasks = list_tasks_week(db, message.from_user.id, start)

    if not tasks:
        await message.answer("На неделю задач нет.")
        return

    out = []
    cur = None
    for t in tasks:
        if cur != t.date:
            cur = t.date
            out.append(f"\n{cur.isoformat()}:")
        out.append(task_line(t))
    await message.answer("\n".join(out).strip())


@dp.message(Command("date"))
async def date_cmd(message: types.Message):
    parts = message.text.split()
    if len(parts) != 2:
        await message.answer("Формат: /date YYYY-MM-DD")
        return
    d = parse_date(parts[1])

    with SessionLocal() as db:
        ensure_repeats_generated(db, message.from_user.id, d)
        tasks = list_tasks_for_date(db, message.from_user.id, d, show="all", category=None)

    if not tasks:
        await message.answer(f"{d.isoformat()}: пусто.")
        return

    await message.answer(f"{d.isoformat()}:\n" + "\n".join(task_line(t) for t in tasks))


@dp.message(Command("search"))
async def search_cmd(message: types.Message):
    q = message.text.replace("/search", "", 1).strip()
    if not q:
        await message.answer('Формат: /search слово')
        return
    with SessionLocal() as db:
        rows = search_tasks(db, message.from_user.id, q)
    if not rows:
        await message.answer("Ничего не найдено.")
        return
    await message.answer("Найдено:\n" + "\n".join(task_line(t) for t in rows))


@dp.message(Command("done"))
async def done_cmd(message: types.Message):
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Формат: /done ID")
        return
    task_id = int(parts[1])
    with SessionLocal() as db:
        ok = set_task_done(db, message.from_user.id, task_id, True)
    await message.answer("Готово." if ok else "Нет такой задачи (или не твоя).")


@dp.message(Command("undo"))
async def undo_cmd(message: types.Message):
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Формат: /undo ID")
        return
    task_id = int(parts[1])
    with SessionLocal() as db:
        ok = set_task_done(db, message.from_user.id, task_id, False)
    await message.answer("Ок." if ok else "Нет такой задачи (или не твоя).")


@dp.message(Command("delete"))
async def delete_cmd(message: types.Message):
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Формат: /delete ID")
        return
    task_id = int(parts[1])
    with SessionLocal() as db:
        ok = delete_task(db, message.from_user.id, task_id)
    await message.answer("Удалено." if ok else "Нет такой задачи (или не твоя).")


@dp.message(Command("move"))
async def move_cmd(message: types.Message):
    parts = message.text.split()
    if len(parts) != 3 or not parts[1].isdigit():
        await message.answer("Формат: /move ID tomorrow|YYYY-MM-DD")
        return
    task_id = int(parts[1])
    if parts[2].lower() == "tomorrow":
        d = date.today() + timedelta(days=1)
    else:
        d = parse_date(parts[2])

    with SessionLocal() as db:
        ok = move_task(db, message.from_user.id, task_id, d)
    await message.answer("Перенёс." if ok else "Нет такой задачи (или не твоя).")


@dp.message(Command("edit"))
async def edit_cmd(message: types.Message):
    parts = message.text.split()
    if len(parts) < 3 or not parts[1].isdigit():
        await message.answer("Формат: /edit ID [HH:MM] [p=..] [m=..] [due=..] [cat=..] [diff=..] текст")
        return

    task_id = int(parts[1])

    time_str = None
    idx = 2
    if idx < len(parts) and valid_time(parts[idx]):
        time_str = parts[idx]
        idx += 1

    params, text = parse_kv_args(parts[idx:])
    p = params.get("p")
    m = int(params["m"]) if "m" in params and params["m"].isdigit() else None
    cat = params.get("cat")
    diff = params.get("diff")
    due = parse_date(params["due"]) if "due" in params else None

    if not text and not params and time_str is None:
        await message.answer("Нечего менять.")
        return

    with SessionLocal() as db:
        ok = edit_task(
            db,
            message.from_user.id,
            task_id,
            time_str=time_str,
            text=text if text else None,
            category=cat,
            priority=p,
            estimated_minutes=m,
            due_date=due,
            difficulty=diff,
        )

    await message.answer("Обновил." if ok else "Нет такой задачи (или не твоя).")


# -------- repeats --------
@dp.message(Command("repeat"))
async def repeat_cmd(message: types.Message):
    raw = message.text.split()
    if len(raw) < 2:
        await message.answer("Формат: /repeat add|list|delete ...")
        return

    action = raw[1].lower()

    if action == "list":
        with SessionLocal() as db:
            reps = list_repeats(db, message.from_user.id)
        if not reps:
            await message.answer("Повторов нет.")
            return
        lines = []
        wd = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
        for r in reps:
            kind = r.kind
            if kind == "weekly":
                kind = f"weekly({wd[r.weekday]})"
            lines.append(f"[{r.id}] {kind} {r.time_str} — {r.text}")
        await message.answer("\n".join(lines))
        return

    if action == "delete":
        if len(raw) != 3 or not raw[2].isdigit():
            await message.answer("Формат: /repeat delete ID")
            return
        rid = int(raw[2])
        with SessionLocal() as db:
            ok = delete_repeat(db, message.from_user.id, rid)
        await message.answer("Удалил." if ok else "Нет такого повтора (или не твой).")
        return

    if action == "add":
        # /repeat add daily 09:00 text...
        if len(raw) < 5:
            await message.answer(
                "Форматы:\n"
                "/repeat add daily HH:MM текст\n"
                "/repeat add weekdays HH:MM текст\n"
                "/repeat add weekly mon|tue|wed|thu|fri|sat|sun HH:MM текст"
            )
            return

        kind = raw[2].lower()
        wd_map = {"mon":0,"tue":1,"wed":2,"thu":3,"fri":4,"sat":5,"sun":6}

        weekday = None
        if kind == "weekly":
            day = raw[3].lower()
            if day not in wd_map:
                await message.answer("Для weekly укажи день: mon/tue/wed/thu/fri/sat/sun")
                return
            weekday = wd_map[day]
            time_str = raw[4]
            text = " ".join(raw[5:]).strip()
        else:
            time_str = raw[3]
            text = " ".join(raw[4:]).strip()

        if kind not in ("daily", "weekdays", "weekly"):
            await message.answer("kind должен быть daily/weekdays/weekly")
            return
        if not valid_time(time_str):
            await message.answer("Время должно быть HH:MM")
            return
        if not text:
            await message.answer("Нет текста.")
            return

        with SessionLocal() as db:
            rid = add_repeat(db, message.from_user.id, kind, time_str, text, weekday=weekday)

        await message.answer(f"Повтор добавлен: ID={rid}")
        return

    await message.answer("Неизвестная команда /repeat.")


# -------- availability / busy --------
@dp.message(Command("availability"))
async def availability_cmd(message: types.Message):
    raw = message.text.split(maxsplit=1)
    if len(raw) != 2 or "-" not in raw[1]:
        await message.answer("Формат: /availability HH:MM-HH:MM")
        return
    a0, a1 = [x.strip() for x in raw[1].split("-", 1)]
    if not (valid_time(a0) and valid_time(a1)):
        await message.answer("Время должно быть HH:MM-HH:MM")
        return
    with SessionLocal() as db:
        set_availability(db, message.from_user.id, date.today(), a0, a1)
    await message.answer(f"Ок, сегодня свободен: {a0}-{a1}")


@dp.message(Command("busy"))
async def busy_cmd(message: types.Message):
    raw = message.text.split(maxsplit=1)
    if len(raw) != 2 or "-" not in raw[1]:
        await message.answer("Формат: /busy HH:MM-HH:MM")
        return
    b0, b1 = [x.strip() for x in raw[1].split("-", 1)]
    if not (valid_time(b0) and valid_time(b1)):
        await message.answer("Время должно быть HH:MM-HH:MM")
        return
    with SessionLocal() as db:
        add_busy(db, message.from_user.id, date.today(), b0, b1)
    await message.answer(f"Добавил занято: {b0}-{b1}")


# -------- mood --------
@dp.message(Command("mood"))
async def mood_cmd(message: types.Message):
    parts = message.text.split()
    if len(parts) < 6:
        await message.answer("Формат: /mood mood sleep focus energy stress\nПример: /mood calm 7.5 clear 8 3")
        return

    mood = parts[1]
    try:
        sleep = float(parts[2])
    except ValueError:
        await message.answer("sleep должно быть числом, например 7.5")
        return
    focus = parts[3]
    try:
        energy = int(parts[4])
        stress = int(parts[5])
    except ValueError:
        await message.answer("energy/stress должны быть целыми")
        return

    with SessionLocal() as db:
        upsert_daily_log(db, message.from_user.id, date.today(), mood=mood, sleep_hours=sleep, focus_level=focus, energy=energy, stress=stress)

    await message.answer("Состояние записано.")


@dp.message(Command("mood_today"))
async def mood_today_cmd(message: types.Message):
    with SessionLocal() as db:
        log = get_daily_log(db, message.from_user.id, date.today())

    if not log:
        await message.answer("На сегодня записи нет.")
        return

    await message.answer(
        "Сегодня:\n"
        f"- mood: {log.mood}\n"
        f"- sleep: {log.sleep_hours}\n"
        f"- focus: {log.focus_level}\n"
        f"- energy: {log.energy}\n"
        f"- stress: {log.stress}"
    )


# -------- plan --------
@dp.message(Command("plan"))
async def plan_cmd(message: types.Message):
    parts = message.text.split()
    action = parts[1].lower() if len(parts) > 1 else "show"

    with SessionLocal() as db:
        ensure_repeats_generated(db, message.from_user.id, date.today())

        if action in ("generate", "regenerate"):
            try:
                pid = generate_plan(db, message.from_user.id, date.today())
                await message.answer(f"План создан (version обновлён). plan_id={pid}\nСмотри: /plan show")
            except RuntimeError as e:
                if str(e) == "PLAN_LOCKED":
                    await message.answer("План зафиксирован. Сними фиксацию (пока не реализовано) или делай план на завтра.")
                else:
                    raise
            return

        if action == "lock":
            ok = lock_plan(db, message.from_user.id, date.today())
            await message.answer("План зафиксирован." if ok else "Плана ещё нет. Сделай /plan generate")
            return

        # show (default)
        pid, ver, locked, items = get_plan_items(db, message.from_user.id, date.today())
        avail, busy = get_availability_and_busy(db, message.from_user.id, date.today())

    if not pid:
        await message.answer("Плана нет. Сделай /plan generate")
        return

    head = f"План на сегодня (v{ver})" + (" [LOCKED]" if locked else "")
    window = f"Окно: {avail[0]}-{avail[1]}" if avail else "Окно: 09:00-21:00"
    busy_txt = ""
    if busy:
        busy_txt = "Занято: " + ", ".join([f"{b0}-{b1}" for b0, b1 in busy])

    if not items:
        await message.answer(f"{head}\n{window}\n{busy_txt}\n\nНичего не удалось поставить в окно.")
        return

    lines = [f"{it.start_time}-{it.end_time}  [{it.task_id}] {it.text}" for it in items]
    msg = "\n".join([head, window, busy_txt, "", *lines]).strip()
    await message.answer(msg)


async def main():
    init_db()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
