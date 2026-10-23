"""O relógio dos prazos. Os prazos legais seguem a LGPD (art. 48) e a Res. CD/ANPD 15/2024; os 'internos' são metas da sua política.

O que o regulamento diz (confirmado em fontes secundárias; confira no texto oficial):
  - comunicar a ANPD e os titulares em 3 DIAS ÚTEIS, contados do conhecimento pelo controlador de que o incidente afetou dados pessoais;
  - agentes de tratamento de pequeno porte: prazo em dobro;
  - informações complementares: 20 dias úteis;
  - ressalva: se a legislação específica (ex.: normas do Banco Central) fixar outro prazo, ele vale."""
from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Dict, List, Optional

from .calendar import Calendar
from .model import from_iso

CFG_DEFAULTS = {"triage_hours": 24, "bcb_hours": None, "operator_hours": 24, "complement_doubles": False, "retention_years": 5}
LEGAL_DAYS, COMPLEMENT_DAYS, DECLARATION_DAYS = 3, 20, 3
STATUS_LABEL = {"cumprido": "Cumprido", "cumprido_atraso": "Cumprido com atraso", "vencido": "VENCIDO", "hoje": "Vence HOJE", "a_vencer": "A vencer"}


def end_of_day(d) -> datetime:
    return datetime.combine(d, time(23, 59))


def _first(comms: List[Dict], dest: str, kind: Optional[str] = None) -> Optional[datetime]:
    times = [from_iso(c["sent_at"]) for c in comms if c["dest"] == dest and (kind is None or c["kind"] == kind) and c["sent_at"]]
    return min(times) if times else None


def _status(due: datetime, done: Optional[datetime], now: datetime) -> str:
    if done:
        return "cumprido" if done <= due else "cumprido_atraso"
    if now > due:
        return "vencido"
    return "hoje" if now.date() == due.date() else "a_vencer"


def _remaining(due: datetime, status: str, now: datetime, cal: Calendar, business: bool) -> str:
    if status in ("cumprido", "cumprido_atraso"):
        return ""
    if business:
        n = cal.business_days_between(now.date(), due.date())
        if status == "vencido":
            return f"vencido há {abs(n)} dia(s) útil(eis)" if n else "vencido"
        return "vence HOJE às 23:59" if status == "hoje" else f"faltam {n} dia(s) útil(eis); vence em {due:%d/%m/%Y} às 23:59"
    hours = (due - now).total_seconds() / 3600
    return f"vencido há {abs(hours):.0f} h" if status == "vencido" else f"restam {hours:.0f} h (até {due:%d/%m %H:%M})"


def compute(inc: Dict, comms: List[Dict], cal: Calendar, now: datetime, cfg: Optional[Dict] = None) -> List[Dict]:
    cfg = {**CFG_DEFAULTS, **(cfg or {})}
    out: List[Dict] = []
    small = inc["small_agent"] == "1"

    def add(key, name, legal, base, due, done, note="", business=True, applies=True):
        status = _status(due, done, now)
        out.append({"key": key, "name": name, "legal": legal, "base_at": base, "due": due, "done_at": done, "status": status,
                    "remaining": _remaining(due, status, now, cal, business), "note": note})

    aware = from_iso(inc["pd_aware_at"])
    if inc["pd_status"] == "sim" and aware and inc["anpd_decision"] != "nao":
        days = LEGAL_DAYS * (2 if small else 1)
        base_note = "prazo em dobro: agente de pequeno porte" if small else ""
        if inc["role"] == "controlador":
            provisional = "prazo provisório: a decisão sobre comunicar ainda não foi registrada" if inc["anpd_decision"] == "pendente" else ""
            due_date = cal.add_business_days(aware.date(), days)
            add("anpd", "Comunicação preliminar à ANPD", True, aware, end_of_day(due_date), _first(comms, "anpd", "preliminar"),
                "; ".join(x for x in (base_note, provisional) if x))
            add("titulares", "Comunicação aos titulares", True, aware, end_of_day(due_date), _first(comms, "titulares"),
                "; ".join(x for x in (base_note, "fontes divergem sobre o prazo para titulares: confirme no texto oficial") if x))
            decl = cal.add_business_days(due_date, DECLARATION_DAYS * (2 if small else 1))
            add("declaracao", "Declaração à ANPD de que os titulares foram comunicados", True, aware, end_of_day(decl), _first(comms, "anpd", "declaracao_titulares"),
                "conforme resumo de escritório de advocacia: confirme no texto oficial")
            prelim = _first(comms, "anpd", "preliminar")
            if prelim:
                mult = 2 if (small and cfg["complement_doubles"]) else 1
                add("complemento", "Informações complementares à ANPD", True, prelim, end_of_day(cal.add_business_days(prelim.date(), COMPLEMENT_DAYS * mult)),
                    _first(comms, "anpd", "complementar"))
        else:
            hours = cfg["operator_hours"]
            add("controlador", "Notificar o controlador (prazo contratual/interno)", False, aware, aware + timedelta(hours=hours), _first(comms, "controlador"),
                f"{hours} h: defina o prazo no contrato com o controlador", business=False)

    detected = from_iso(inc["detected_at"])
    triaged = inc["pd_status"] != "investigando" and inc["anpd_decision"] != "pendente" or inc["pd_status"] == "nao"
    if detected and inc["status"] != "encerrado":
        add("triagem", "Triagem: dados pessoais afetados? comunicar? (meta interna)", False, detected, detected + timedelta(hours=cfg["triage_hours"]),
            now if triaged else None, "meta interna", business=False)
        if triaged:
            out[-1]["done_at"], out[-1]["status"], out[-1]["remaining"] = None, "cumprido", ""
    if cfg["bcb_hours"] and inc["bcb_relevant"] == "sim" and detected:
        add("bcb", "Comunicação ao Banco Central (prazo interno)", False, detected, detected + timedelta(hours=cfg["bcb_hours"]), _first(comms, "bcb"),
            "a Res. CMN 4.893 exige comunicação tempestiva: defina o prazo na sua política", business=False)
    return out


def retain_until(inc: Dict, years: int = 5) -> Optional[datetime]:
    base = from_iso(inc["closed_at"]) or from_iso(inc["detected_at"])
    if not base:
        return None
    try:
        return base.replace(year=base.year + years)
    except ValueError:                                   # 29 de fevereiro
        return base.replace(year=base.year + years, day=28)
