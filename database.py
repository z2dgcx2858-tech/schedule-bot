# database.py
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, date, time, timedelta
from typing import Optional, List, Tuple

from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    DateTime,
    Date,
    Boolean,
    ForeignKey,
    UniqueConstraint,
    select,
    and_,
    or_,
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set")

# SQLAlchemy prefers postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


# ---------------- DTO ----------------
@dataclass
class TaskRow:
    id: int
    date: date
    start_time: str
    text: str
    category: Optional[str]
    done: bool
    priority: Optional[str]
    estimated_minutes: Optional[int]
    due_date: Optional[date]
    difficulty: Optional[str]


@dataclass
class DailyLogDTO:
    mood: Optional[str]
    sleep_hours: Optional[float]
    focus_level: Optional[str]
    energy: Optional[int]
    stress: Optional[int]


@dataclass
class PlanItemDTO:
    task_id: int
    start_time: str
    end_time: str
    text: str


# ---------------- MODELS ----------------
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    tg_id = Column(Integer, unique=True, nullable=False, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class Task(Base):
    __tablename__ = "tasks"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    date = Column(Date, nullable=False, index=True)
    start_time = Column(String, nullable=True)  # HH:MM (может быть None, если планируем автоматически)
    text = Column(String, nullable=False)
    category = Column(String, nullable=True)
    done = Column(Boolean, default=False)

    priority = Column(String, nullable=True)          # low/med/high
    estimated_minutes = Column(Integer, nullable=True)
    due_date = Column(Date, nullable=True)
    difficulty = Column(String, nullable=True)        # easy/med/hard

    source_repeat_id = Column(Integer, ForeignKey("recurring_tasks.id"), nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        # чтобы автогенерация из повторов не плодила дубликаты на одну дату
        UniqueConstraint("user_id", "date", "source_repeat_id", name="uq_task_repeat_per_day"),
    )


class DailyLog(Base):
    __tablename__ = "daily_logs"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)

    mood = Column(String, nullable=True)
    sleep_hours = Column(String, nullable=True)   # хранить как текст можно, но оставим строкой? лучше float, но не критично
    focus_level = Column(String, nullable=True)
    energy = Column(Integer, nullable=True)
    stress = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("user_id", "date", name="uq_daily_log_user_date"),)


class RecurringTask(Base):
    __tablename__ = "recurring_tasks"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    kind = Column(String, nullable=False)  # daily | weekdays | weekly
    weekday = Column(Integer, nullable=True)  # 0=Mon..6=Sun (for weekly)
    time_str = Column(String, nullable=False)  # HH:MM

    text = Column(String, nullable=False)
    category = Column(String, nullable=True)
    priority = Column(String, nullable=True)
    estimated_minutes = Column(Integer, nullable=True)
    difficulty = Column(String, nullable=True)

    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class Availability(Base):
    __tablename__ = "availability"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    start_time = Column(String, nullable=False)
    end_time = Column(String, nullable=False)

    __table_args__ = (UniqueConstraint("user_id", "date", "start_time", "end_time", name="uq_avail"),)


class BusyBlock(Base):
    __tablename__ = "busy_blocks"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    start_time = Column(String, nullable=False)
    end_time = Column(String, nullable=False)


class Plan(Base):
    __tablename__ = "plans"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    version = Column(Integer, nullable=False, default=1)
    is_locked = Column(Boolean, default=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("user_id", "date", "version", name="uq_plan_version"),)


class PlanItem(Base):
    __tablename__ = "plan_items"
    id = Column(Integer, primary_key=True)
    plan_id = Column(Integer, ForeignKey("plans.id"), nullable=False, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False)
    start_time = Column(String, nullable=False)
    end_time = Column(String, nullable=False)


# ---------------- INIT ----------------
def init_db() -> None:
    Base.metadata.create_all(bind=engine)


# ---------------- HELPERS ----------------
def _get_or_create_user_id(db, tg_id: int) -> int:
    u = db.execute(select(User).where(User.tg_id == tg_id)).scalar_one_or_none()
    if u:
        return u.id
    u = User(tg_id=tg_id)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u.id


def _parse_hhmm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def _time_to_minutes(t: time) -> int:
    return t.hour * 60 + t.minute


def _minutes_to_hhmm(x: int) -> str:
    x = max(0, x)
    h = x // 60
    m = x % 60
    return f"{h:02d}:{m:02d}"


# ---------------- TASKS ----------------
def add_task(
    db,
    tg_id: int,
    date_obj: date,
    time_str: Optional[str],
    text: str,
    category: Optional[str] = None,
    priority: Optional[str] = None,
    estimated_minutes: Optional[int] = None,
    due_date: Optional[date] = None,
    difficulty: Optional[str] = None,
) -> int:
    user_id = _get_or_create_user_id(db, tg_id)
    t = Task(
        user_id=user_id,
        date=date_obj,
        start_time=time_str,
        text=text,
        category=category,
        done=False,
        priority=priority,
        estimated_minutes=estimated_minutes,
        due_date=due_date,
        difficulty=difficulty,
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t.id


def get_task_owner_id(db, task_id: int) -> Optional[int]:
    row = db.execute(select(Task.user_id).where(Task.id == task_id)).first()
    return row[0] if row else None


def set_task_done(db, tg_id: int, task_id: int, done: bool) -> bool:
    user_id = _get_or_create_user_id(db, tg_id)
    t = db.execute(select(Task).where(Task.id == task_id, Task.user_id == user_id)).scalar_one_or_none()
    if not t:
        return False
    t.done = done
    db.commit()
    return True


def delete_task(db, tg_id: int, task_id: int) -> bool:
    user_id = _get_or_create_user_id(db, tg_id)
    t = db.execute(select(Task).where(Task.id == task_id, Task.user_id == user_id)).scalar_one_or_none()
    if not t:
        return False
    db.delete(t)
    db.commit()
    return True


def move_task(db, tg_id: int, task_id: int, new_date: date) -> bool:
    user_id = _get_or_create_user_id(db, tg_id)
    t = db.execute(select(Task).where(Task.id == task_id, Task.user_id == user_id)).scalar_one_or_none()
    if not t:
        return False
    t.date = new_date
    db.commit()
    return True


def edit_task(
    db,
    tg_id: int,
    task_id: int,
    time_str: Optional[str] = None,
    text: Optional[str] = None,
    category: Optional[str] = None,
    priority: Optional[str] = None,
    estimated_minutes: Optional[int] = None,
    due_date: Optional[date] = None,
    difficulty: Optional[str] = None,
) -> bool:
    user_id = _get_or_create_user_id(db, tg_id)
    t = db.execute(select(Task).where(Task.id == task_id, Task.user_id == user_id)).scalar_one_or_none()
    if not t:
        return False

    if time_str is not None:
        t.start_time = time_str
    if text is not None:
        t.text = text
    if category is not None:
        t.category = category
    if priority is not None:
        t.priority = priority
    if estimated_minutes is not None:
        t.estimated_minutes = estimated_minutes
    if due_date is not None:
        t.due_date = due_date
    if difficulty is not None:
        t.difficulty = difficulty

    db.commit()
    return True


def list_tasks_for_date(
    db,
    tg_id: int,
    date_obj: date,
    show: str = "all",  # all|done|todo
    category: Optional[str] = None,
) -> List[TaskRow]:
    user_id = _get_or_create_user_id(db, tg_id)

    conditions = [Task.user_id == user_id, Task.date == date_obj]
    if show == "done":
        conditions.append(Task.done.is_(True))
    elif show == "todo":
        conditions.append(Task.done.is_(False))
    if category:
        conditions.append(Task.category == category)

    rows = db.execute(
        select(
            Task.id,
            Task.date,
            Task.start_time,
            Task.text,
            Task.category,
            Task.done,
            Task.priority,
            Task.estimated_minutes,
            Task.due_date,
            Task.difficulty,
        )
        .where(and_(*conditions))
        .order_by(Task.start_time.asc().nullslast(), Task.id.asc())
    ).all()

    out: List[TaskRow] = []
    for r in rows:
        out.append(
            TaskRow(
                id=r[0],
                date=r[1],
                start_time=r[2] or "--:--",
                text=r[3],
                category=r[4],
                done=bool(r[5]),
                priority=r[6],
                estimated_minutes=r[7],
                due_date=r[8],
                difficulty=r[9],
            )
        )
    return out


def list_tasks_week(db, tg_id: int, start_date: date) -> List[TaskRow]:
    user_id = _get_or_create_user_id(db, tg_id)
    end_date = start_date + timedelta(days=7)

    rows = db.execute(
        select(
            Task.id, Task.date, Task.start_time, Task.text, Task.category, Task.done,
            Task.priority, Task.estimated_minutes, Task.due_date, Task.difficulty
        )
        .where(Task.user_id == user_id, Task.date >= start_date, Task.date < end_date)
        .order_by(Task.date.asc(), Task.start_time.asc().nullslast(), Task.id.asc())
    ).all()

    return [
        TaskRow(
            id=r[0],
            date=r[1],
            start_time=r[2] or "--:--",
            text=r[3],
            category=r[4],
            done=bool(r[5]),
            priority=r[6],
            estimated_minutes=r[7],
            due_date=r[8],
            difficulty=r[9],
        )
        for r in rows
    ]


def search_tasks(db, tg_id: int, q: str, limit: int = 30) -> List[TaskRow]:
    user_id = _get_or_create_user_id(db, tg_id)
    like = f"%{q}%"
    rows = db.execute(
        select(
            Task.id, Task.date, Task.start_time, Task.text, Task.category, Task.done,
            Task.priority, Task.estimated_minutes, Task.due_date, Task.difficulty
        )
        .where(Task.user_id == user_id, Task.text.ilike(like))
        .order_by(Task.date.desc(), Task.start_time.asc().nullslast())
        .limit(limit)
    ).all()

    return [
        TaskRow(
            id=r[0],
            date=r[1],
            start_time=r[2] or "--:--",
            text=r[3],
            category=r[4],
            done=bool(r[5]),
            priority=r[6],
            estimated_minutes=r[7],
            due_date=r[8],
            difficulty=r[9],
        )
        for r in rows
    ]


# ---------------- DAILY LOG ----------------
def upsert_daily_log(
    db,
    tg_id: int,
    date_obj: date,
    mood: Optional[str] = None,
    sleep_hours: Optional[float] = None,
    focus_level: Optional[str] = None,
    energy: Optional[int] = None,
    stress: Optional[int] = None,
) -> None:
    user_id = _get_or_create_user_id(db, tg_id)
    log = db.execute(
        select(DailyLog).where(DailyLog.user_id == user_id, DailyLog.date == date_obj)
    ).scalar_one_or_none()

    if log is None:
        log = DailyLog(user_id=user_id, date=date_obj)
        db.add(log)

    if mood is not None:
        log.mood = mood
    if sleep_hours is not None:
        log.sleep_hours = str(sleep_hours)
    if focus_level is not None:
        log.focus_level = focus_level
    if energy is not None:
        log.energy = int(energy)
    if stress is not None:
        log.stress = int(stress)

    db.commit()


def get_daily_log(db, tg_id: int, date_obj: date) -> Optional[DailyLogDTO]:
    user_id = _get_or_create_user_id(db, tg_id)
    log = db.execute(
        select(DailyLog).where(DailyLog.user_id == user_id, DailyLog.date == date_obj)
    ).scalar_one_or_none()

    if not log:
        return None

    sleep_val: Optional[float] = None
    if log.sleep_hours is not None:
        try:
            sleep_val = float(log.sleep_hours)
        except ValueError:
            sleep_val = None

    return DailyLogDTO(
        mood=log.mood,
        sleep_hours=sleep_val,
        focus_level=log.focus_level,
        energy=log.energy,
        stress=log.stress,
    )


# ---------------- REPEATS ----------------
def add_repeat(
    db,
    tg_id: int,
    kind: str,
    time_str: str,
    text: str,
    weekday: Optional[int] = None,
    category: Optional[str] = None,
    priority: Optional[str] = None,
    estimated_minutes: Optional[int] = None,
    difficulty: Optional[str] = None,
) -> int:
    user_id = _get_or_create_user_id(db, tg_id)
    r = RecurringTask(
        user_id=user_id,
        kind=kind,
        weekday=weekday,
        time_str=time_str,
        text=text,
        category=category,
        priority=priority,
        estimated_minutes=estimated_minutes,
        difficulty=difficulty,
        is_active=True,
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    return r.id


def list_repeats(db, tg_id: int) -> List[RecurringTask]:
    user_id = _get_or_create_user_id(db, tg_id)
    return db.execute(
        select(RecurringTask).where(RecurringTask.user_id == user_id, RecurringTask.is_active.is_(True))
        .order_by(RecurringTask.id.asc())
    ).scalars().all()


def delete_repeat(db, tg_id: int, repeat_id: int) -> bool:
    user_id = _get_or_create_user_id(db, tg_id)
    r = db.execute(
        select(RecurringTask).where(RecurringTask.id == repeat_id, RecurringTask.user_id == user_id)
    ).scalar_one_or_none()
    if not r:
        return False
    r.is_active = False
    db.commit()
    return True


def ensure_repeats_generated(db, tg_id: int, date_obj: date) -> None:
    """Создаёт задачи на дату из активных повторов (без дублей)."""
    user_id = _get_or_create_user_id(db, tg_id)
    dow = date_obj.weekday()  # 0..6

    repeats = db.execute(
        select(RecurringTask).where(
            RecurringTask.user_id == user_id,
            RecurringTask.is_active.is_(True),
            or_(
                RecurringTask.kind == "daily",
                and_(RecurringTask.kind == "weekdays", dow <= 4),
                and_(RecurringTask.kind == "weekly", RecurringTask.weekday == dow),
            ),
        )
    ).scalars().all()

    for r in repeats:
        # вставка задачи с source_repeat_id; uq гарантирует отсутствие дублей
        t = Task(
            user_id=user_id,
            date=date_obj,
            start_time=r.time_str,
            text=r.text,
            category=r.category,
            done=False,
            priority=r.priority,
            estimated_minutes=r.estimated_minutes,
            difficulty=r.difficulty,
            source_repeat_id=r.id,
        )
        db.add(t)

    try:
        db.commit()
    except Exception:
        # если часть задач уже есть — uq может триггернуть; откатим и продолжим
        db.rollback()


# ---------------- AVAILABILITY / BUSY ----------------
def set_availability(db, tg_id: int, date_obj: date, start_time: str, end_time: str) -> None:
    user_id = _get_or_create_user_id(db, tg_id)
    # перезапишем на день (простая модель)
    db.execute(select(Availability).where(Availability.user_id == user_id, Availability.date == date_obj))
    db.query(Availability).filter(Availability.user_id == user_id, Availability.date == date_obj).delete()
    db.add(Availability(user_id=user_id, date=date_obj, start_time=start_time, end_time=end_time))
    db.commit()


def add_busy(db, tg_id: int, date_obj: date, start_time: str, end_time: str) -> None:
    user_id = _get_or_create_user_id(db, tg_id)
    db.add(BusyBlock(user_id=user_id, date=date_obj, start_time=start_time, end_time=end_time))
    db.commit()


def get_availability_and_busy(db, tg_id: int, date_obj: date) -> Tuple[Optional[Tuple[str, str]], List[Tuple[str, str]]]:
    user_id = _get_or_create_user_id(db, tg_id)
    a = db.execute(select(Availability).where(Availability.user_id == user_id, Availability.date == date_obj)).scalar_one_or_none()
    avail = (a.start_time, a.end_time) if a else None
    busy = db.execute(select(BusyBlock.start_time, BusyBlock.end_time).where(BusyBlock.user_id == user_id, BusyBlock.date == date_obj)).all()
    return avail, [(b[0], b[1]) for b in busy]


# ---------------- PLANS ----------------
def _current_plan(db, user_id: int, date_obj: date) -> Optional[Plan]:
    return db.execute(
        select(Plan).where(Plan.user_id == user_id, Plan.date == date_obj).order_by(Plan.version.desc())
    ).scalars().first()


def plan_is_locked(db, tg_id: int, date_obj: date) -> bool:
    user_id = _get_or_create_user_id(db, tg_id)
    p = _current_plan(db, user_id, date_obj)
    return bool(p and p.is_locked)


def lock_plan(db, tg_id: int, date_obj: date) -> bool:
    user_id = _get_or_create_user_id(db, tg_id)
    p = _current_plan(db, user_id, date_obj)
    if not p:
        return False
    p.is_locked = True
    db.commit()
    return True


def generate_plan(db, tg_id: int, date_obj: date) -> int:
    """Создаёт новый план (новая версия) и items, возвращает plan_id."""
    user_id = _get_or_create_user_id(db, tg_id)

    cur = _current_plan(db, user_id, date_obj)
    if cur and cur.is_locked:
        raise RuntimeError("PLAN_LOCKED")

    next_version = (cur.version + 1) if cur else 1
    p = Plan(user_id=user_id, date=date_obj, version=next_version, is_locked=False)
    db.add(p)
    db.commit()
    db.refresh(p)

    # удалить items если вдруг
    db.query(PlanItem).filter(PlanItem.plan_id == p.id).delete()
    db.commit()

    # расписание: берём TODO задачи на дату
    tasks = db.execute(
        select(Task).where(Task.user_id == user_id, Task.date == date_obj, Task.done.is_(False))
        .order_by(Task.start_time.asc().nullslast(), Task.id.asc())
    ).scalars().all()

    avail, busy = get_availability_and_busy(db, tg_id, date_obj)
    if not avail:
        # если не задано — дефолт окно 09:00–21:00
        avail = ("09:00", "21:00")

    avail_start = _time_to_minutes(_parse_hhmm(avail[0]))
    avail_end = _time_to_minutes(_parse_hhmm(avail[1]))

    busy_ranges = []
    for b0, b1 in busy:
        busy_ranges.append((_time_to_minutes(_parse_hhmm(b0)), _time_to_minutes(_parse_hhmm(b1))))
    busy_ranges.sort()

    def is_free(slot_start: int, slot_end: int) -> bool:
        if slot_start < avail_start or slot_end > avail_end:
            return False
        for bs, be in busy_ranges:
            if not (slot_end <= bs or slot_start >= be):
                return False
        return True

    cursor = avail_start
    for t in tasks:
        dur = t.estimated_minutes or 30
        # если у задачи задано start_time — попробуем поставить туда
        if t.start_time and t.start_time != "--:--":
            s = _time_to_minutes(_parse_hhmm(t.start_time))
            e = s + dur
            if is_free(s, e):
                db.add(PlanItem(plan_id=p.id, task_id=t.id, start_time=_minutes_to_hhmm(s), end_time=_minutes_to_hhmm(e)))
                continue

        # иначе — найдём ближайший свободный слот
        placed = False
        probe = cursor
        while probe + dur <= avail_end:
            if is_free(probe, probe + dur):
                db.add(PlanItem(plan_id=p.id, task_id=t.id, start_time=_minutes_to_hhmm(probe), end_time=_minutes_to_hhmm(probe + dur)))
                cursor = probe + dur
                placed = True
                break
            probe += 5  # шаг 5 минут
        if not placed:
            # не влезло — пропускаем (можно потом улучшить)
            continue

    db.commit()
    return p.id


def get_plan_items(db, tg_id: int, date_obj: date) -> Tuple[Optional[int], Optional[int], bool, List[PlanItemDTO]]:
    """Возвращает (plan_id, version, locked, items)."""
    user_id = _get_or_create_user_id(db, tg_id)
    p = _current_plan(db, user_id, date_obj)
    if not p:
        return None, None, False, []

    items = db.execute(
        select(PlanItem.start_time, PlanItem.end_time, Task.id, Task.text)
        .join(Task, Task.id == PlanItem.task_id)
        .where(PlanItem.plan_id == p.id)
        .order_by(PlanItem.start_time.asc())
    ).all()

    dto = [PlanItemDTO(task_id=i[2], start_time=i[0], end_time=i[1], text=i[3]) for i in items]
    return p.id, p.version, bool(p.is_locked), dto
