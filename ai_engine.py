# ai_engine.py
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass
class TaskIn:
    id: int
    text: str
    duration_min: int = 30
    fixed_start_hhmm: Optional[str] = None  # если есть фиксированное время


@dataclass
class PlanItemOut:
    task_id: int
    start_hhmm: str
    end_hhmm: str


def hhmm_to_minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def minutes_to_hhmm(x: int) -> str:
    h = x // 60
    m = x % 60
    return f"{h:02d}:{m:02d}"


def merge_ranges(ranges: List[Tuple[int, int]]) -> List[Tuple[int, int]]:
    if not ranges:
        return []
    ranges = sorted(ranges)
    merged = [ranges[0]]
    for s, e in ranges[1:]:
        ps, pe = merged[-1]
        if s <= pe:
            merged[-1] = (ps, max(pe, e))
        else:
            merged.append((s, e))
    return merged


def free_windows(avail: Tuple[str, str], busy: List[Tuple[str, str]], min_window: int = 10) -> List[Tuple[int, int]]:
    a0 = hhmm_to_minutes(avail[0])
    a1 = hhmm_to_minutes(avail[1])

    busy_m = [(hhmm_to_minutes(s), hhmm_to_minutes(e)) for s, e in busy]
    busy_m = merge_ranges(busy_m)

    windows: List[Tuple[int, int]] = [(a0, a1)]
    for bs, be in busy_m:
        new: List[Tuple[int, int]] = []
        for ws, we in windows:
            if be <= ws or bs >= we:
                new.append((ws, we))
            else:
                if ws < bs:
                    new.append((ws, bs))
                if be < we:
                    new.append((be, we))
        windows = new

    return [(s, e) for s, e in windows if e - s >= min_window]


def _cut_window(windows: List[Tuple[int, int]], idx: int, cut_s: int, cut_e: int, min_window: int = 10) -> None:
    """Вырезает [cut_s, cut_e) из windows[idx], обновляя список."""
    ws, we = windows[idx]
    new_parts: List[Tuple[int, int]] = []
    if ws < cut_s:
        new_parts.append((ws, cut_s))
    if cut_e < we:
        new_parts.append((cut_e, we))

    windows.pop(idx)
    for part in reversed(new_parts):
        if part[1] - part[0] >= min_window:
            windows.insert(idx, part)


def place_fixed(windows: List[Tuple[int, int]], start_min: int, dur: int) -> Optional[Tuple[int, int]]:
    end_min = start_min + dur
    for i, (ws, we) in enumerate(windows):
        if start_min >= ws and end_min <= we:
            _cut_window(windows, i, start_min, end_min)
            return start_min, end_min
    return None


def place_first_fit(windows: List[Tuple[int, int]], dur: int) -> Optional[Tuple[int, int]]:
    for i, (ws, we) in enumerate(windows):
        if we - ws >= dur:
            start = ws
            end = ws + dur
            _cut_window(windows, i, start, end)
            return start, end
    return None


def build_plan(
    tasks: List[TaskIn],
    avail: Tuple[str, str],
    busy: List[Tuple[str, str]],
) -> Tuple[List[PlanItemOut], List[int]]:
    """
    Возвращает:
      - plan_items: список (task_id, start, end)
      - not_scheduled_task_ids: какие не влезли
    Логика этапа 1:
      - сначала ставим фиксированные задачи
      - потом остальные подряд по свободным слотам
    """
    windows = free_windows(avail, busy)

    # 1) фиксированные
    plan: List[PlanItemOut] = []
    used = set()

    fixed = [t for t in tasks if t.fixed_start_hhmm]
    nonfixed = [t for t in tasks if not t.fixed_start_hhmm]

    for t in fixed:
        s = hhmm_to_minutes(t.fixed_start_hhmm)  # type: ignore[arg-type]
        got = place_fixed(windows, s, t.duration_min)
        if got:
            smin, emin = got
            plan.append(PlanItemOut(t.id, minutes_to_hhmm(smin), minutes_to_hhmm(emin)))
            used.add(t.id)

    # 2) остальные
    for t in nonfixed:
        got = place_first_fit(windows, t.duration_min)
        if got:
            smin, emin = got
            plan.append(PlanItemOut(t.id, minutes_to_hhmm(smin), minutes_to_hhmm(emin)))
            used.add(t.id)

    plan.sort(key=lambda x: hhmm_to_minutes(x.start_hhmm))
    not_scheduled = [t.id for t in tasks if t.id not in used]
    return plan, not_scheduled
