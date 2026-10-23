"""Operações do registro: abrir, atualizar, anotar, comunicar, decidir, encerrar, prazos, rascunhos e métricas.

Princípios de integridade: a data de detecção NÃO pode ser alterada; mudar a data de conhecimento exige motivo; a decisão de comunicar
(ou não) exige justificativa; e tudo vira evento na trilha de auditoria encadeada por hash."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional, Union

from . import deadlines as dl, triage
from .calendar import Calendar
from .model import (CATEGORIES, COMM_KIND, COMM_TO, DECISIONS, PD_STATUS, ROLES, SEVERITIES, STATUSES, TRI, ValidationError, check_text, choice, from_iso, iso,
                    parse_dt, parse_flags)
from .store import Store

FIELD_LABEL = {"title": "título", "description": "descrição", "category": "categoria", "severity": "gravidade", "status": "status", "pd_status": "dados pessoais afetados",
               "pd_aware_at": "data de conhecimento", "data_flags": "tipos de dados", "affected_count": "titulares", "significant_impact": "impacto significativo",
               "role": "papel", "small_agent": "pequeno porte", "anpd_decision": "decisão sobre a ANPD", "anpd_justification": "justificativa", "bcb_relevant": "relevante para o BC",
               "systems": "sistemas", "vendor": "fornecedor", "owner": "responsável", "root_cause": "causa raiz", "lessons": "lições aprendidas", "contained_at": "contido em",
               "resolved_at": "resolvido em", "closed_at": "encerrado em", "occurred_at": "ocorrido em", "detected_at": "detectado em"}
LONG_TEXT = ("description", "root_cause", "lessons", "anpd_justification")
EDITABLE = {"title", "description", "category", "severity", "status", "pd_status", "pd_aware_at", "data_flags", "affected_count", "significant_impact", "role",
            "small_agent", "bcb_relevant", "systems", "vendor", "owner", "occurred_at", "root_cause", "lessons"}
TEXT_FIELDS = {"title": "título", "description": "descrição", "systems": "campo de sistemas", "vendor": "campo do fornecedor", "owner": "responsável",
               "root_cause": "campo de causa raiz", "lessons": "campo de lições aprendidas"}


class Desk:
    def __init__(self, store: Store, calendar: Optional[Calendar] = None, cfg: Optional[Dict] = None,
                 now: Union[None, datetime, Callable[[], datetime]] = None, actor: str = "analista"):
        self.store, self.cal, self.cfg, self._now, self.actor = store, calendar or Calendar(), {**dl.CFG_DEFAULTS, **(cfg or {})}, now, actor
        self.warnings: List[str] = []

    def now(self) -> datetime:
        n = self._now() if callable(self._now) else self._now
        return (n or datetime.now()).replace(second=0, microsecond=0)

    # ---- utilitários -------------------------------------------------------------------------------------------------------------
    def _text(self, value: str, label: str) -> str:
        self.warnings += check_text(value or "", label)
        return (value or "").strip()

    def _get(self, iid: str) -> Dict:
        inc = self.store.incident(iid.upper())
        if not inc:
            raise ValidationError(f"incidente {iid} não encontrado")
        return inc

    @staticmethod
    def _count(value) -> str:
        if value in (None, ""):
            return ""
        try:
            n = int(str(value).replace(".", "").strip())
        except ValueError:
            raise ValidationError(f"número de titulares inválido: '{value}'") from None
        if n < 0:
            raise ValidationError("o número de titulares não pode ser negativo")
        return str(n)

    # ---- abrir e atualizar -------------------------------------------------------------------------------------------------------
    def new(self, title: str, description: str = "", category: str = "outro", severity: str = "media", detected_at=None, occurred_at=None,
            pd_status: str = "investigando", pd_aware_at=None, data_flags="", affected_count=None, significant_impact: str = "avaliando",
            role: str = "controlador", small_agent: bool = False, bcb_relevant: str = "avaliando", systems: str = "", vendor: str = "", owner: str = "") -> str:
        self.warnings = []
        if not (title or "").strip():
            raise ValidationError("informe o título do incidente")
        now = self.now()
        detected = parse_dt(detected_at, "data de detecção") or now
        if detected > now + timedelta(minutes=5):
            raise ValidationError("a data de detecção está no futuro")
        pd = choice(pd_status, PD_STATUS, "situação dos dados pessoais")
        aware = parse_dt(pd_aware_at, "data de conhecimento") or (detected if pd == "sim" else None)
        fields = {"title": self._text(title, "título"), "description": self._text(description, "descrição"), "category": choice(category, CATEGORIES, "categoria"),
                  "severity": choice(severity, SEVERITIES, "gravidade"), "status": "aberto", "detected_at": iso(detected), "occurred_at": iso(parse_dt(occurred_at, "data de ocorrência")),
                  "pd_status": pd, "pd_aware_at": iso(aware) if pd == "sim" else "", "data_flags": parse_flags(data_flags), "affected_count": self._count(affected_count),
                  "significant_impact": choice(significant_impact, TRI, "impacto significativo"), "role": choice(role, ROLES, "papel"),
                  "small_agent": "1" if small_agent else "0", "anpd_decision": "nao" if pd == "nao" else "pendente",
                  "anpd_justification": "Sem dados pessoais afetados (registrado na abertura)" if pd == "nao" else "", "bcb_relevant": choice(bcb_relevant, TRI, "relevância para o Banco Central"),
                  "systems": self._text(systems, "campo de sistemas"), "vendor": self._text(vendor, "campo do fornecedor"), "owner": self._text(owner, "responsável")}
        iid = self.store.create(fields, now, self.actor)
        return iid

    def update(self, iid: str, reason: str = "", **changes) -> Dict[str, List[str]]:
        self.warnings = []
        inc, now = self._get(iid), self.now()
        iid = inc["id"]
        bad = set(changes) - EDITABLE
        if bad:
            hint = {"detected_at": "a data de detecção não pode ser alterada", "anpd_decision": "use 'decide'", "closed_at": "use 'close'"}.get(next(iter(bad)), "campo não editável")
            raise ValidationError(f"{', '.join(sorted(bad))}: {hint}")
        if inc["status"] == "encerrado" and "status" not in changes:
            raise ValidationError("incidente encerrado: reabra-o (status) para alterá-lo")
        new: Dict[str, str] = {}
        for k, v in changes.items():
            if k in TEXT_FIELDS:
                new[k] = self._text(v, TEXT_FIELDS[k])
            elif k == "category":
                new[k] = choice(v, CATEGORIES, "categoria")
            elif k == "severity":
                new[k] = choice(v, SEVERITIES, "gravidade")
            elif k == "status":
                new[k] = choice(v, STATUSES, "status")
            elif k == "pd_status":
                new[k] = choice(v, PD_STATUS, "situação dos dados pessoais")
            elif k in ("significant_impact", "bcb_relevant"):
                new[k] = choice(v, TRI, k)
            elif k == "role":
                new[k] = choice(v, ROLES, "papel")
            elif k == "data_flags":
                new[k] = parse_flags(v)
            elif k == "affected_count":
                new[k] = self._count(v)
            elif k == "small_agent":
                new[k] = "1" if v in (True, "1", "sim", "true") else "0"
            elif k in ("pd_aware_at", "occurred_at"):
                new[k] = iso(parse_dt(v, k))
        if new.get("status") == "encerrado":
            raise ValidationError("para encerrar use o comando 'close' (exige a causa raiz)")
        if "pd_aware_at" in new and inc["pd_aware_at"] and new["pd_aware_at"] != inc["pd_aware_at"]:
            if len((reason or "").strip()) < 10:
                raise ValidationError("mudar a data de conhecimento altera o prazo legal: informe o motivo (mínimo 10 caracteres)")
        pd_new = new.get("pd_status", inc["pd_status"])
        if pd_new == "sim" and not (new.get("pd_aware_at") or inc["pd_aware_at"]):
            new["pd_aware_at"] = iso(now)                                   # o relógio começa quando se confirma que houve dados pessoais
        if "pd_status" in new and new["pd_status"] == "nao" and inc["anpd_decision"] == "pendente":
            new["anpd_decision"], new["anpd_justification"] = "nao", "Sem dados pessoais afetados (confirmado na triagem)"
        if "pd_status" in new and inc["pd_status"] == "nao" and new["pd_status"] != "nao":
            new["anpd_decision"], new["anpd_justification"] = "pendente", ""
        if new.get("status") == "contido" and not inc["contained_at"]:
            new["contained_at"] = iso(now)
        if new.get("status") == "recuperado" and not inc["resolved_at"]:
            new["resolved_at"] = iso(now)
        if inc["status"] == "encerrado" and "status" in new:
            new["closed_at"] = ""                                           # reabertura
        diff = self.store.update(iid, new, now, self.actor)
        if "pd_aware_at" in diff and reason:
            self.store.note(iid, "correcao", f"Data de conhecimento alterada. Motivo: {self._text(reason, 'motivo')}", now, self.actor)
        return diff

    def note(self, iid: str, text: str, kind: str = "nota") -> None:
        self.warnings = []
        inc = self._get(iid)
        if not (text or "").strip():
            raise ValidationError("informe o texto da anotação")
        self.store.note(inc["id"], kind or "nota", self._text(text, "texto da anotação"), self.now(), self.actor)

    def comm(self, iid: str, dest: str, kind: str = "preliminar", sent_at=None, ref: str = "", notes: str = "") -> int:
        self.warnings = []
        inc, now = self._get(iid), self.now()
        dest, kind = choice(dest, COMM_TO, "destinatário"), choice(kind, COMM_KIND, "tipo da comunicação")
        sent = parse_dt(sent_at, "data do envio") or now
        if sent > now + timedelta(minutes=5):
            raise ValidationError("a data do envio está no futuro")
        cid = self.store.add_comm(inc["id"], dest, kind, iso(sent), self._text(ref, "protocolo"), self._text(notes, "observação"), now, self.actor)
        if dest == "anpd" and kind == "preliminar" and inc["anpd_decision"] != "sim":
            self.store.update(inc["id"], {"anpd_decision": "sim", "anpd_justification": f"Comunicação à ANPD registrada em {sent:%d/%m/%Y %H:%M}"}, now, self.actor)
        return cid

    def decide(self, iid: str, anpd: str, justification: str) -> None:
        """Registra se haverá comunicação à ANPD e por quê. Decisão sem justificativa não vale como evidência."""
        self.warnings = []
        inc, now = self._get(iid), self.now()
        decision = choice(anpd, ("sim", "nao"), "decisão")
        text = self._text(justification, "texto da justificativa")
        if len(text) < 15:
            raise ValidationError("a justificativa é obrigatória (mínimo 15 caracteres): é ela que prova que o risco foi avaliado")
        self.store.update(inc["id"], {"anpd_decision": decision, "anpd_justification": text}, now, self.actor)
        self.store.note(inc["id"], "decisao", f"Comunicação à ANPD: {'SIM' if decision == 'sim' else 'NÃO'}. {text}", now, self.actor)
        if decision == "nao" and triage.assess(self._get(inc["id"]))["probable"]:
            self.warnings.append("a avaliação do art. 5º indica provável risco relevante: confirme essa decisão com o encarregado e o jurídico")

    def close(self, iid: str, root_cause: str = "", lessons: str = "", closed_at=None, force: bool = False) -> None:
        self.warnings = []
        inc, now = self._get(iid), self.now()
        if not (root_cause or "").strip() and not force:
            raise ValidationError("informe a causa raiz (--root-cause) para encerrar. Use --force só em caso excepcional")
        if inc["pd_status"] != "nao" and inc["anpd_decision"] == "pendente" and not force:
            raise ValidationError("há dados pessoais envolvidos e a decisão sobre comunicar a ANPD ainda está pendente: registre-a (decide) antes de encerrar")
        changes = {"status": "encerrado", "closed_at": iso(parse_dt(closed_at, "data de encerramento") or now)}
        if root_cause.strip():
            changes["root_cause"] = self._text(root_cause, "campo de causa raiz")
        if lessons.strip():
            changes["lessons"] = self._text(lessons, "campo de lições aprendidas")
        if not inc["resolved_at"]:
            changes["resolved_at"] = changes["closed_at"]
        self.store.update(inc["id"], changes, now, self.actor)

    # ---- prazos, avaliação e rascunhos -------------------------------------------------------------------------------------------
    def deadlines(self, iid: str) -> List[Dict]:
        inc = self._get(iid)
        return dl.compute(inc, self.store.comms(inc["id"]), self.cal, self.now(), self.cfg)

    def all_deadlines(self, open_only: bool = True) -> List[Dict]:
        out = []
        for inc in self.store.incidents():
            if open_only and inc["status"] == "encerrado":
                continue
            for d in dl.compute(inc, self.store.comms(inc["id"]), self.cal, self.now(), self.cfg):
                out.append({**d, "incident": inc})
        order = {"vencido": 0, "hoje": 1, "a_vencer": 2, "cumprido_atraso": 3, "cumprido": 4}
        return sorted(out, key=lambda d: (order[d["status"]], d["due"]))

    def assessment(self, iid: str) -> Dict:
        return triage.assess(self._get(iid))

    def draft(self, iid: str, kind: str = "anpd") -> str:
        inc = self._get(iid)
        notes = [{"kind": e["kind"], "text": e["text"]} for e in self.timeline(inc["id"]) if e["event"] == "note"]
        if kind == "titulares":
            return triage.draft_titulares(inc, notes)
        late = any(d["key"] == "anpd" and d["status"] in ("vencido", "cumprido_atraso") for d in self.deadlines(inc["id"]))
        return triage.draft_anpd(inc, notes, late)

    def timeline(self, iid: str) -> List[Dict]:
        import json
        out = []
        for e in self.store.events(iid):
            p = json.loads(e["payload"])
            if e["kind"] == "note":
                out.append({"ts": e["ts"], "actor": e["actor"], "event": "note", "kind": p["kind"], "text": p["text"]})
            elif e["kind"] == "comm":
                out.append({"ts": e["ts"], "actor": e["actor"], "event": "comm", "kind": "comunicacao",
                            "text": f"{p['kind']} para {p['dest']} em {p['sent_at'].replace('T', ' ')}" + (f" (protocolo {p['ref']})" if p["ref"] else "")})
            elif e["kind"] == "created":
                out.append({"ts": e["ts"], "actor": e["actor"], "event": "created", "kind": "abertura", "text": "Incidente registrado"})
            elif e["kind"] == "updated":
                out.append({"ts": e["ts"], "actor": e["actor"], "event": "updated", "kind": "alteracao",
                            "text": "; ".join(f"{FIELD_LABEL.get(k, k)}: '{v[0].replace('T', ' ')}' → '{v[1].replace('T', ' ')}'" if k not in LONG_TEXT else f"{FIELD_LABEL.get(k, k)} atualizado" for k, v in p["changes"].items())})
        return out

    def retain_until(self, inc: Dict) -> Optional[datetime]:
        return dl.retain_until(inc, self.cfg["retention_years"])

    def verify(self) -> List[str]:
        return self.store.verify()

    # ---- métricas ----------------------------------------------------------------------------------------------------------------
    def metrics(self) -> Dict:
        incidents, now = self.store.incidents(), self.now()
        m: Dict = {"total": len(incidents), "open": 0, "by_severity": {}, "by_category": {}, "required": 0, "on_time": 0, "late": 0, "overdue": 0,
                   "decision_pending": 0, "triage_overdue": 0, "closed_without_cause": 0, "hours_to_contain": [], "hours_to_resolve": []}
        for inc in incidents:
            m["by_severity"][inc["severity"]] = m["by_severity"].get(inc["severity"], 0) + 1
            m["by_category"][inc["category"]] = m["by_category"].get(inc["category"], 0) + 1
            det = from_iso(inc["detected_at"])
            if inc["status"] != "encerrado":
                m["open"] += 1
            if inc["status"] == "encerrado" and not inc["root_cause"].strip():
                m["closed_without_cause"] += 1
            if det and from_iso(inc["contained_at"]):
                m["hours_to_contain"].append((from_iso(inc["contained_at"]) - det).total_seconds() / 3600)
            if det and from_iso(inc["resolved_at"]):
                m["hours_to_resolve"].append((from_iso(inc["resolved_at"]) - det).total_seconds() / 3600)
            if inc["pd_status"] != "nao" and inc["anpd_decision"] == "pendente" and inc["status"] != "encerrado":
                m["decision_pending"] += 1
            for d in dl.compute(inc, self.store.comms(inc["id"]), self.cal, now, self.cfg):
                if d["key"] == "triagem" and d["status"] == "vencido":
                    m["triage_overdue"] += 1
                if d["key"] == "anpd":
                    m["required"] += 1
                    m["on_time"] += d["status"] == "cumprido"
                    m["late"] += d["status"] == "cumprido_atraso"
                    m["overdue"] += d["status"] == "vencido"
        avg = lambda xs: round(sum(xs) / len(xs), 1) if xs else None  # noqa: E731
        m["avg_hours_to_contain"], m["avg_hours_to_resolve"] = avg(m.pop("hours_to_contain")), avg(m.pop("hours_to_resolve"))
        return m
