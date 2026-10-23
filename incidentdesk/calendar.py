"""Calendário de DIAS ÚTEIS: fins de semana e feriados nacionais. O prazo da ANPD é contado em dias úteis.

Regra de contagem usada (a usual para prazos): o dia do conhecimento NÃO conta; o 1º dia útil é o seguinte; o prazo vence no
fim do último dia. Feriados estaduais e municipais, e pontos facultativos, dependem do seu caso: informe-os em um arquivo
(--holidays) para não errar o prazo. Confirme a contagem com o jurídico."""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Dict, Optional

# feriados nacionais de data fixa: (mês, dia) -> nome
FIXED = {(1, 1): "Confraternização Universal", (4, 21): "Tiradentes", (5, 1): "Dia do Trabalho", (9, 7): "Independência do Brasil",
         (10, 12): "Nossa Senhora Aparecida", (11, 2): "Finados", (11, 15): "Proclamação da República", (12, 25): "Natal"}
BLACK_CONSCIOUSNESS = ((11, 20), "Dia da Consciência Negra")      # feriado nacional a partir de 2024 (Lei 14.759/2023)


def easter(year: int) -> date:
    """Domingo de Páscoa (algoritmo de Meeus/Jones/Butcher, calendário gregoriano)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def national_holidays(year: int, optional_points: bool = False) -> Dict[date, str]:
    out = {date(year, m, d): name for (m, d), name in FIXED.items()}
    out[easter(year) - timedelta(days=2)] = "Sexta-feira Santa"
    if year >= 2024:
        (m, d), name = BLACK_CONSCIOUSNESS
        out[date(year, m, d)] = name
    if optional_points:             # pontos facultativos: só entram se você pedir
        e = easter(year)
        out[e - timedelta(days=48)] = "Carnaval (segunda-feira)"
        out[e - timedelta(days=47)] = "Carnaval (terça-feira)"
        out[e + timedelta(days=60)] = "Corpus Christi"
    return out


def load_holidays(path: str) -> Dict[date, str]:
    """Arquivo texto: uma data por linha ('AAAA-MM-DD' ou 'dd/mm/aaaa'), com nome opcional depois. '#' começa comentário."""
    out: Dict[date, str] = {}
    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            text = line.split("#", 1)[0].strip()
            if not text:
                continue
            m = re.match(r"(\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4})\s*(.*)", text)
            if not m:
                raise ValueError(f"linha de feriado inválida: {text!r}")
            raw = m.group(1)
            d = date.fromisoformat(raw) if "-" in raw else date(int(raw[6:]), int(raw[3:5]), int(raw[:2]))
            out[d] = m.group(2).strip() or "Feriado informado"
    return out


class Calendar:
    def __init__(self, extra: Optional[Dict[date, str]] = None, optional_points: bool = False):
        self.extra = dict(extra or {})
        self.optional_points = optional_points
        self._cache: Dict[int, Dict[date, str]] = {}

    def holiday(self, d: date) -> Optional[str]:
        if d.year not in self._cache:
            self._cache[d.year] = national_holidays(d.year, self.optional_points)
        return self.extra.get(d) or self._cache[d.year].get(d)

    def is_business_day(self, d: date) -> bool:
        return d.weekday() < 5 and self.holiday(d) is None

    def add_business_days(self, start: date, n: int) -> date:
        """O dia 'start' não conta; devolve o n-ésimo dia útil depois dele."""
        d, left = start, n
        while left > 0:
            d += timedelta(days=1)
            if self.is_business_day(d):
                left -= 1
        return d

    def business_days_between(self, start: date, end: date) -> int:
        """Dias úteis em (start, end]: negativo se 'end' é anterior a 'start'."""
        if end < start:
            return -self.business_days_between(end, start)
        count, d = 0, start
        while d < end:
            d += timedelta(days=1)
            if self.is_business_day(d):
                count += 1
        return count
