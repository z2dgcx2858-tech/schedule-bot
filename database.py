# database.py
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, date
from typing import Optional, List, Tuple

from sqlalchemy import (
    create_engine,
    String,
    Integer,
    Date,
    DateTime,
    Boolean,
    ForeignKey,
    Text,
    UniqueConstraint,
    select,
    delete,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker, Session

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set")

# Railway часто даёт postgres:// вместо postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tg_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)

    date: Mapped[date] = mapped_column(Date, nullable=False)
    start_time: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)  # HH:MM (фикс)
    text: Mapped[str] = mapped_column(Text, nullable=False)

    done: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # для этапа 1: длительность (если нет — будем считать 30)
    estimated_minutes: Mapped[int] = mapped_column(Integer, default=30, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class Availability(Base):
    __tablename__ = "availability"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    start_time: Mapped[str] = mapped_column(String(5), nullable=False)  # HH:MM
    end_time: Mapped[str] = mapped_column(String(5), nullable=False)    # HH:MM
    __table_args__ = (UniqueConstraint("user_id", "date", name="uq_availability_user_date"),)


class BusyBlock(Base):
    __tablename__ = "busy_blocks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    start_time: Mapped[str] = mapped_column(String(5), nullable=False)
    end_time: Mapped[str] = mapped_column(String(5), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class Plan(Base):
    __tablename__ = "plans"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    items: Mapped[List["PlanItem"]] = relationship(back_populates="plan", cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint("user_id", "date", name="uq_plan_user_date"),)


class PlanItem(Base):
    __tablename__ = "plan_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id"), nullable=False)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), nullable=False)
    start_time: Mapped[str] = mapped_column(String(5), nullable=False)
    end_time: Mapped[str] = mapped_column(String(5), nullable=False)

    plan: Mapped[Plan] = relationship(back_populates="items")


@dataclass
class TaskDTO:
    id: int
    start_time: Optional[str]
    text: str
    done: bool
    estimated_minutes: int


def init_db() -> None:
    Base.metadata.create_all(engine)


def _get_or_create_user_id(db: Session, tg_id: int) -> int:
    u = db.execute(select(User).where(User.tg_id == tg_id)).scalar_one_or_none()
    if u:
        return u.id
    u = User(tg_id=tg_id)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u.id


# ---------- tasks ----------
def add_task(db: Session, tg_id: int, date_obj: date, time_str: Optional[str], text: str, minutes: int = 30) -> None:
    user_id = _get_or_create_user_id(db, tg_id)
    t = Task(user_id=user_id, date=date_obj, start_time=time_str, text=text, estimated_minutes=minutes)
    db.add(t)
    db.commit()


def get_tasks_for_date(db: Session, tg_id: int, date_obj: date) -> List[TaskDTO]:
    user_id = _get_or_create_user_id(db, tg_id)
    rows = db.execute(
        select(Task).where(Task.user_id == user_id, Task.date == date_obj).order_by(Task.start_time.is_(None), Task.start_time.asc())
    ).scalars().all()
    return [
        TaskDTO(id=r.id, start_time=r.start_time, text=r.text, done=r.done, estimated_minutes=r.estimated_minutes)
        for r in rows
    ]


def get_todo_tasks_for_date(db: Session, tg_id: int, date_obj: date) -> List[Task]:
    user_id = _get_or_create_user_id(db, tg_id)
    return db.execute(
        select(Task).where(Task.user_id == user_id, Task.date == date_obj, Task.done.is_(False))
    ).scalars().all()


def set_task_done(db: Session, tg_id: int, task_id: int, done: bool) -> bool:
    user_id = _get_or_create_user_id(db, tg_id)
    t = db.execute(select(Task).where(Task.id == task_id, Task.user_id == user_id)).scalar_one_or_none()
    if not t:
        return False
    t.done = done
    db.commit()
    return True


# ---------- availability / busy ----------
def set_availability(db: Session, tg_id: int, date_obj: date, start_hhmm: str, end_hhmm: str) -> None:
    user_id = _get_or_create_user_id(db, tg_id)
    row = db.execute(select(Availability).where(Availability.user_id == user_id, Availability.date == date_obj)).scalar_one_or_none()
    if row:
        row.start_time = start_hhmm
        row.end_time = end_hhmm
    else:
        db.add(Availability(user_id=user_id, date=date_obj, start_time=start_hhmm, end_time=end_hhmm))
    db.commit()


def add_busy(db: Session, tg_id: int, date_obj: date, start_hhmm: str, end_hhmm: str) -> None:
    user_id = _get_or_create_user_id(db, tg_id)
    db.add(BusyBlock(user_id=user_id, date=date_obj, start_time=start_hhmm, end_time=end_hhmm))
    db.commit()


def get_availability_and_busy(db: Session, tg_id: int, date_obj: date) -> Tuple[Tuple[str, str], List[Tuple[str, str]]]:
    user_id = _get_or_create_user_id(db, tg_id)

    av = db.execute(select(Availability).where(Availability.user_id == user_id, Availability.date == date_obj)).scalar_one_or_none()
    if av:
        avail = (av.start_time, av.end_time)
    else:
        avail = ("09:00", "21:00")  # дефолт

    busy_rows = db.execute(
        select(BusyBlock).where(BusyBlock.user_id == user_id, BusyBlock.date == date_obj).order_by(BusyBlock.start_time.asc())
    ).scalars().all()
    busy = [(b.start_time, b.end_time) for b in busy_rows]

    return avail, busy


# ---------- plan ----------
def generate_plan(db: Session, tg_id: int, date_obj: date) -> Tuple[int, List[int]]:
    """
    Этап 1:
      - берём TODO задачи
      - берём availability и busy
      - строим простой план
      - сохраняем в plans/plan_items
    Возвращает:
      plan_id, not_scheduled_task_ids
    """
    from ai_engine import TaskIn, build_plan

    user_id = _get_or_create_user_id(db, tg_id)

    # удалить старый план на эту дату (чтобы /plan_generate пересчитывал)
    old = db.execute(select(Plan).where(Plan.user_id == user_id, Plan.date == date_obj)).scalar_one_or_none()
    if old:
        db.execute(delete(Plan).where(Plan.id == old.id))
        db.commit()

    plan = Plan(user_id=user_id, date=date_obj)
    db.add(plan)
    db.commit()
    db.refresh(plan)

    avail, busy = get_availability_and_busy(db, tg_id, date_obj)

    tasks = get_todo_tasks_for_date(db, tg_id, date_obj)
    tasks_in = [
        TaskIn(
            id=t.id,
            text=t.text,
            duration_min=t.estimated_minutes or 30,
            fixed_start_hhmm=t.start_time,
        )
        for t in tasks
    ]

    items, not_scheduled = build_plan(tasks_in, avail, busy)

    for it in items:
        db.add(PlanItem(plan_id=plan.id, task_id=it.task_id, start_time=it.start_hhmm, end_time=it.end_hhmm))

    db.commit()
    return plan.id, not_scheduled


def get_plan(db: Session, tg_id: int, date_obj: date) -> Optional[Tuple[int, List[Tuple[str, str, int, str]]]]:
    """
    Возвращает:
      (plan_id, [(start, end, task_id, task_text), ...])
    """
    user_id = _get_or_create_user_id(db, tg_id)
    p = db.execute(select(Plan).where(Plan.user_id == user_id, Plan.date == date_obj)).scalar_one_or_none()
    if not p:
        return None

    rows = db.execute(
        select(PlanItem.start_time, PlanItem.end_time, Task.id, Task.text)
        .join(Task, Task.id == PlanItem.task_id)
        .where(PlanItem.plan_id == p.id)
        .order_by(PlanItem.start_time.asc())
    ).all()

    items = [(r[0], r[1], r[2], r[3]) for r in rows]
    return p.id, items
