# database.py
from __future__ import annotations

import sqlite3
from datetime import datetime, date
from dataclasses import dataclass
from typing import Optional, List, Any


DB_PATH = "planner.db"


# ---------- DTO-КЛАССЫ (чтобы main.py мог обращаться к .start_time, .text и т.д.) ----------

@dataclass
class TaskDTO:
    start_time: str
    text: str


@dataclass
class DailyLogDTO:
    mood: Optional[str]
    sleep_hours: Optional[float]
    focus_level: Optional[str]
    energy: Optional[int]
    stress: Optional[int]


# ---------- БАЗОВЫЕ ВЕЩИ ----------

def get_connection() -> sqlite3.Connection:
    """
    Открывает соединение с SQLite.
    В main.py мы будем делать: `with SessionLocal() as db: ...`,
    поэтому SessionLocal = get_connection.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# Чтобы main.py не менять, делаем псевдо SessionLocal
SessionLocal = get_connection


def init_db() -> None:
    """
    Создаёт таблицы, если их ещё нет.
    Вызывается один раз при старте бота.
    """
    with get_connection() as conn:
        cur = conn.cursor()

        # Пользователи
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tg_id INTEGER UNIQUE NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )

        # Задачи
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                date TEXT NOT NULL,           -- YYYY-MM-DD
                start_time TEXT NOT NULL,     -- '14:30'
                end_time TEXT,                -- пока не используем
                text TEXT NOT NULL,
                category TEXT,
                done INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
            """
        )

        # Ежедневные логи (настроение, сон и т.д.)
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                date TEXT NOT NULL,          -- YYYY-MM-DD
                mood TEXT,
                sleep_hours REAL,
                focus_level TEXT,
                energy INTEGER,
                stress INTEGER,
                created_at TEXT NOT NULL,
                UNIQUE(user_id, date),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
            """
        )

        conn.commit()


# ---------- ВСПОМОГАТЕЛЬНОЕ ----------

def _get_or_create_user(conn: sqlite3.Connection, tg_id: int) -> int:
    """
    Возвращает внутренний id пользователя по tg_id.
    Если пользователя нет — создаёт.
    """
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE tg_id = ?", (tg_id,))
    row = cur.fetchone()
    if row:
        return row["id"]

    now = datetime.utcnow().isoformat()
    cur.execute(
        "INSERT INTO users (tg_id, created_at) VALUES (?, ?)",
        (tg_id, now),
    )
    conn.commit()
    return cur.lastrowid


# ---------- ЗАДАЧИ ----------

def add_task(
    conn: sqlite3.Connection,
    tg_id: int,
    date_obj: date,
    time_str: str,
    text: str,
    category: Optional[str] = None,
) -> None:
    """
    Добавляет задачу пользователю на указанную дату и время.
    """
    user_id = _get_or_create_user(conn, tg_id)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO tasks (user_id, date, start_time, text, category, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (user_id, date_obj.isoformat(), time_str, text, category, datetime.utcnow().isoformat()),
    )
    conn.commit()


def get_tasks_for_date(
    conn: sqlite3.Connection,
    tg_id: int,
    date_obj: date,
) -> List[TaskDTO]:
    """
    Возвращает список задач на указанную дату как объекты TaskDTO
    с полями .start_time и .text (под main.py).
    """
    user_id = _get_or_create_user(conn, tg_id)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT start_time, text
        FROM tasks
        WHERE user_id = ? AND date = ?
        ORDER BY start_time ASC
        """,
        (user_id, date_obj.isoformat()),
    )
    rows = cur.fetchall()
    return [TaskDTO(start_time=row["start_time"], text=row["text"]) for row in rows]


# ---------- ДНЕВНИК СОСТОЯНИЯ ----------

def upsert_daily_log(
    conn: sqlite3.Connection,
    tg_id: int,
    date_obj: date,
    mood: Optional[str] = None,
    sleep_hours: Optional[float] = None,
    focus_level: Optional[str] = None,
    energy: Optional[int] = None,
    stress: Optional[int] = None,
) -> None:
    """
    Создаёт или обновляет запись за день.
    Любой параметр, который не None, будет записан/обновлён.
    """
    user_id = _get_or_create_user(conn, tg_id)
    cur = conn.cursor()

    cur.execute(
        "SELECT id FROM daily_logs WHERE user_id = ? AND date = ?",
        (user_id, date_obj.isoformat()),
    )
    row = cur.fetchone()

    now = datetime.utcnow().isoformat()

    if row is None:
        # создаём новую запись
        cur.execute(
            """
            INSERT INTO daily_logs
            (user_id, date, mood, sleep_hours, focus_level, energy, stress, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                date_obj.isoformat(),
                mood,
                sleep_hours,
                focus_level,
                energy,
                stress,
                now,
            ),
        )
    else:
        # обновляем существующую
        updates = []
        params: list[Any] = []

        if mood is not None:
            updates.append("mood = ?")
            params.append(mood)
        if sleep_hours is not None:
            updates.append("sleep_hours = ?")
            params.append(sleep_hours)
        if focus_level is not None:
            updates.append("focus_level = ?")
            params.append(focus_level)
        if energy is not None:
            updates.append("energy = ?")
            params.append(energy)
        if stress is not None:
            updates.append("stress = ?")
            params.append(stress)

        if updates:
            sql = f"UPDATE daily_logs SET {', '.join(updates)} WHERE user_id = ? AND date = ?"
            params.extend([user_id, date_obj.isoformat()])
            cur.execute(sql, tuple(params))

    conn.commit()


def get_daily_log(
    conn: sqlite3.Connection,
    tg_id: int,
    date_obj: date,
) -> Optional[DailyLogDTO]:
    """
    Возвращает одну запись дневника за день как DailyLogDTO
    с полями .mood, .sleep_hours, .focus_level, .energy, .stress,
    либо None, если записи нет.
    """
    user_id = _get_or_create_user(conn, tg_id)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT mood, sleep_hours, focus_level, energy, stress
        FROM daily_logs
        WHERE user_id = ? AND date = ?
        """,
        (user_id, date_obj.isoformat()),
    )
    row = cur.fetchone()
    if row is None:
        return None

    return DailyLogDTO(
        mood=row["mood"],
        sleep_hours=row["sleep_hours"],
        focus_level=row["focus_level"],
        energy=row["energy"],
        stress=row["stress"],
    )
