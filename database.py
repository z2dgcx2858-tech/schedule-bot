# database.py
from datetime import datetime, date
from typing import Optional, List

from sqlalchemy import (
    create_engine, Column, Integer, String,
    DateTime, Date, Float, Boolean
)
from sqlalchemy.orm import declarative_base, sessionmaker

# -------- 1. Подключение к SQLite --------
# Файл planner.db появится в папке проекта
DATABASE_URL = "sqlite:///planner.db"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False}  # нужно для SQLite + asyncio
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


# -------- 2. Таблицы (модели) --------

class User(Base):
    """
    Пользователь Telegram.
    tg_id = message.from_user.id
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    tg_id = Column(Integer, unique=True, index=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class Task(Base):
    """
    Задачи / расписание (то, что сейчас делает /add и /today).
    """
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True, nullable=False)

    date = Column(Date, index=True, nullable=False)     # день задачи
    start_time = Column(String, nullable=False)         # "14:30"
    end_time = Column(String, nullable=True)            # можно пока не использовать
    text = Column(String, nullable=False)
    category = Column(String, nullable=True)            # "deep_work", "mood" и т.п.
    done = Column(Boolean, default=False)

    created_at = Column(DateTime, default=datetime.utcnow)


class DailyLog(Base):
    """
    Ежедневное состояние: настроение, сон, фокус, энергия, стресс.
    """
    __tablename__ = "daily_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True, nullable=False)

    date = Column(Date, index=True, nullable=False)

    mood = Column(String, nullable=True)         # "calm", "neutral", "happy" и т.п.
    sleep_hours = Column(Float, nullable=True)   # 7.5
    focus_level = Column(String, nullable=True)  # "clear", "foggy"
    energy = Column(Integer, nullable=True)      # 1–10
    stress = Column(Integer, nullable=True)      # 1–10

    created_at = Column(DateTime, default=datetime.utcnow)


# -------- 3. СОЗДАТЬ ТАБЛИЦЫ --------

def init_db() -> None:
    """
    Вызвать один раз при старте бота.
    Создаст файл planner.db и таблицы, если их ещё нет.
    """
    Base.metadata.create_all(bind=engine)


# -------- 4. Утилиты для работы с БД --------

def get_or_create_user(db, tg_id: int) -> User:
    """
    Найти пользователя по tg_id, если нет — создать.
    """
    user = db.query(User).filter(User.tg_id == tg_id).first()
    if user:
        return user
    user = User(tg_id=tg_id)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# === Работа с задачами ===

def add_task(
    db,
    tg_id: int,
    date_obj: date,
    time_str: str,
    text: str,
    category: Optional[str] = None
) -> Task:
    """
    Добавить задачу пользователю.
    """
    user = get_or_create_user(db, tg_id=tg_id)

    task = Task(
        user_id=user.id,
        date=date_obj,
        start_time=time_str,
        text=text,
        category=category,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def get_tasks_for_date(db, tg_id: int, date_obj: date) -> List[Task]:
    """
    Получить задачи пользователя на конкретную дату.
    """
    user = get_or_create_user(db, tg_id=tg_id)

    tasks = (
        db.query(Task)
        .filter(Task.user_id == user.id, Task.date == date_obj)
        .order_by(Task.start_time.asc())
        .all()
    )
    return tasks


# === Работа с дневником состояния ===

def upsert_daily_log(
    db,
    tg_id: int,
    date_obj: date,
    mood: Optional[str] = None,
    sleep_hours: Optional[float] = None,
    focus_level: Optional[str] = None,
    energy: Optional[int] = None,
    stress: Optional[int] = None,
) -> DailyLog:
    """
    Создать или обновить запись о состоянии за день.
    """
    user = get_or_create_user(db, tg_id=tg_id)

    log = (
        db.query(DailyLog)
        .filter(DailyLog.user_id == user.id, DailyLog.date == date_obj)
        .first()
    )

    if not log:
        log = DailyLog(user_id=user.id, date=date_obj)

    if mood is not None:
        log.mood = mood
    if sleep_hours is not None:
        log.sleep_hours = sleep_hours
    if focus_level is not None:
        log.focus_level = focus_level
    if energy is not None:
        log.energy = energy
    if stress is not None:
        log.stress = stress

    db.add(log)
    db.commit()
    db.refresh(log)
    return log


def get_daily_log(db, tg_id: int, date_obj: date) -> Optional[DailyLog]:
    """
    Получить дневную запись пользователя за конкретный день.
    """
    user = get_or_create_user(db, tg_id=tg_id)

    log = (
        db.query(DailyLog)
        .filter(DailyLog.user_id == user.id, DailyLog.date == date_obj)
        .first()
    )
    return log
