"""Saídas: terminal, painel HTML, CSV do registro, métricas, ComplianceMap e feed do Venator.

Confidencialidade: o registro descreve incidentes reais (fraquezas, sistemas, volumes). As exportações para o ComplianceMap e o Venator
são AGREGADAS e NÃO levam títulos nem descrições."""
from __future__ import annotations

import csv
import html
import io
import json
import time
from datetime import datetime
from typing import Dict, List

from .desk import Desk
from .deadlines import STATUS_LABEL
from .model import SEVERITY_TO_FEED, from_iso

ANSI = {"vencido": "\033[1;97;41m", "hoje": "\033[1;31m", "a_vencer": "\033[1;33m", "cumprido": "\033[32m", "cumprido_atraso": "\033[33m", "b": "\033[1m", "d": "\033[2m", "x": "\033[0m"}
COLOR = {"vencido": "#ff5c7a", "hoje": "#ff9a45", "a_vencer": "#f2cd3b", "cumprido": "#3ddc84", "cumprido_atraso": "#f2cd3b",
         "critica": "#ff5c7a", "alta": "#ff9a45", "media": "#f2cd3b", "baixa": "#5aa9ff"}
CSV_PREFIX = ("=", "+", "-", "@", "\t", "\r")


def _safe(v):
    return ("'" + v) if isinstance(v, str) and v.startswith(CSV_PREFIX) else v


def _fmt(dt) -> str:
    return dt.strftime("%d/%m/%Y %H:%M") if dt else "—"


def render_deadlines(desk: Desk, color: bool = False, show_done: bool = False) -> str:
    p = (lambda t, k: f"{ANSI[k]}{t}{ANSI['x']}") if color else (lambda t, k: t)
    now = desk.now()
    rows = [d for d in desk.all_deadlines() if show_done or d["status"] not in ("cumprido", "cumprido_atraso")]
    lines = [p("RELÓGIO DOS PRAZOS", "b"), f"Agora: {_fmt(now)}  ·  dias úteis = segunda a sexta, exceto feriados nacionais (e os que você informou)", ""]
    if not rows:
        lines.append("Nenhum prazo em aberto.")
    for d in rows:
        inc = d["incident"]
        tag = "LEI" if d["legal"] else "meta"
        lines.append(f"{p('[' + STATUS_LABEL[d['status']] + ']', d['status'])} {inc['id']}  {d['name']}  ({tag})")
        lines.append(f"      {inc['title'][:70]}")
        lines.append(f"      prazo: {_fmt(d['due'])}  ·  base: {_fmt(d['base_at'])}" + (f"  ·  {d['remaining']}" if d["remaining"] else ""))
        if d["note"]:
            lines.append(p(f"      obs.: {d['note']}", "d"))
    lines += ["", p("Prazo legal (LEI): LGPD art. 48 e Res. CD/ANPD 15/2024. 'meta' = prazo interno da sua política. Confirme a contagem com o jurídico.", "d")]
    return "\n".join(lines)


def render_list(desk: Desk, all_incidents: bool = False) -> str:
    rows = [i for i in desk.store.incidents() if all_incidents or i["status"] != "encerrado"]
    lines = [f"{'ID':<14}{'GRAV.':<9}{'STATUS':<16}{'DADOS PESSOAIS':<16}{'ANPD':<10}TÍTULO"]
    for i in rows:
        lines.append(f"{i['id']:<14}{i['severity']:<9}{i['status']:<16}{i['pd_status']:<16}{i['anpd_decision']:<10}{i['title'][:50]}")
    return "\n".join(lines) if rows else "Nenhum incidente."


def render_incident(desk: Desk, iid: str) -> str:
    inc = desk._get(iid)
    a = desk.assessment(inc["id"])
    lines = [f"{inc['id']}  ·  {inc['title']}", f"Categoria: {inc['category']}  ·  gravidade: {inc['severity']}  ·  status: {inc['status']}  ·  papel: {inc['role']}"
             + ("  ·  agente de pequeno porte" if inc["small_agent"] == "1" else ""),
             f"Detectado: {_fmt(from_iso(inc['detected_at']))}  ·  soube de dados pessoais: {_fmt(from_iso(inc['pd_aware_at']))}  ·  contido: {_fmt(from_iso(inc['contained_at']))}  ·  encerrado: {_fmt(from_iso(inc['closed_at']))}",
             f"Dados pessoais: {inc['pd_status']}  ·  titulares: {inc['affected_count'] or '—'}  ·  tipos: {inc['data_flags'] or '—'}", f"Sistemas: {inc['systems'] or '—'}  ·  fornecedor: {inc['vendor'] or '—'}  ·  responsável: {inc['owner'] or '—'}", ""]
    if inc["description"]:
        lines += [inc["description"], ""]
    lines += ["AVALIAÇÃO (art. 5º da Res. 15/2024): " + a["summary"]]
    if a["criteria"]:
        lines.append("  critérios presentes: " + "; ".join(a["criteria"]))
    lines.append(f"DECISÃO sobre comunicar a ANPD: {inc['anpd_decision'].upper()}" + (f" — {inc['anpd_justification']}" if inc["anpd_justification"] else ""))
    lines += ["", "PRAZOS"]
    for d in desk.deadlines(inc["id"]):
        lines.append(f"  [{STATUS_LABEL[d['status']]}] {d['name']}: {_fmt(d['due'])}" + (f"  ({d['remaining']})" if d["remaining"] else "") + (f"  — enviado {_fmt(d['done_at'])}" if d["done_at"] else ""))
    until = desk.retain_until(inc)
    lines += [f"  Guarda do registro: até {until:%d/%m/%Y} (5 anos)" if until else "", "", "COMUNICAÇÕES"]
    comms = desk.store.comms(inc["id"])
    lines += [f"  {_fmt(from_iso(c['sent_at']))}  {c['kind']} → {c['dest']}" + (f"  protocolo {c['ref']}" if c["ref"] else "") for c in comms] or ["  nenhuma registrada"]
    lines += ["", "LINHA DO TEMPO"] + [f"  {t['ts'].replace('T', ' ')[:16]}  [{t['kind']}] {t['text']}" for t in desk.timeline(inc["id"])]
    if inc["root_cause"]:
        lines += ["", f"CAUSA RAIZ: {inc['root_cause']}"]
    if inc["lessons"]:
        lines.append(f"LIÇÕES APRENDIDAS: {inc['lessons']}")
    return "\n".join(l for l in lines if l is not None)


def render_metrics(desk: Desk) -> str:
    m = desk.metrics()
    problems = desk.verify()
    lines = ["MÉTRICAS", f"Incidentes: {m['total']} ({m['open']} em aberto)", "Por gravidade: " + (" · ".join(f"{k} {v}" for k, v in m["by_severity"].items()) or "—"),
             "Por categoria: " + (" · ".join(f"{k} {v}" for k, v in m["by_category"].items()) or "—"),
             f"Comunicação à ANPD exigida: {m['required']}  →  no prazo {m['on_time']}  ·  com atraso {m['late']}  ·  vencida e não enviada {m['overdue']}",
             f"Decisão sobre comunicar pendente: {m['decision_pending']}  ·  triagem fora da meta: {m['triage_overdue']}  ·  encerrados sem causa raiz: {m['closed_without_cause']}",
             f"Tempo médio até conter: {m['avg_hours_to_contain'] if m['avg_hours_to_contain'] is not None else '—'} h  ·  até resolver: {m['avg_hours_to_resolve'] if m['avg_hours_to_resolve'] is not None else '—'} h",
             "Integridade do registro: " + ("OK (cadeia de hashes íntegra)" if not problems else f"PROBLEMAS ({len(problems)}): rode 'verify'")]
    return "\n".join(lines)


def register_csv(desk: Desk) -> str:
    """O registro para auditoria (inclui incidentes que NÃO foram comunicados, que também devem ser guardados por 5 anos)."""
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\n")
    w.writerow(["id", "titulo", "categoria", "gravidade", "status", "detectado_em", "conhecimento_dados_pessoais_em", "dados_pessoais", "tipos_de_dados", "titulares",
                "decisao_anpd", "justificativa_da_decisao", "causa_raiz", "encerrado_em", "guardar_ate"])
    for i in desk.store.incidents():
        until = desk.retain_until(i)
        w.writerow([i["id"], _safe(i["title"]), i["category"], i["severity"], i["status"], i["detected_at"], i["pd_aware_at"], i["pd_status"], i["data_flags"],
                    i["affected_count"], i["anpd_decision"], _safe(i["anpd_justification"]), _safe(i["root_cause"]), i["closed_at"], f"{until:%Y-%m-%d}" if until else ""])
    return buf.getvalue()


def to_compliancemap(desk: Desk) -> str:
    """Evidência automática AGREGADA para o ComplianceMap (--auto): MON-03 (registro e análise) e MON-04 (comunicação em 3 dias úteis)."""
    m, problems, incidents = desk.metrics(), desk.verify(), desk.store.incidents()
    rows = []
    if not incidents:
        rows = [{"check": "incidentdesk", "control": c, "status": "unknown", "detail": "nenhum incidente registrado", "platform": "ir"} for c in ("MON-03", "MON-04")]
    else:
        bad03 = [x for x in (f"{m['closed_without_cause']} encerrado(s) sem causa raiz" if m["closed_without_cause"] else "",
                             f"integridade do registro comprometida ({len(problems)})" if problems else "") if x]
        rows.append({"check": "incidentdesk", "control": "MON-03", "status": "fail" if bad03 else "pass",
                     "detail": ("; ".join(bad03)) if bad03 else f"{m['total']} incidente(s) registrados, com causa raiz nos encerrados e trilha íntegra", "platform": "ir"})
        with_pd = [i for i in incidents if i["pd_status"] != "nao"]
        bad04 = [x for x in (f"{m['overdue']} comunicação(ões) vencida(s) e não enviada(s)" if m["overdue"] else "", f"{m['late']} comunicação(ões) enviada(s) com atraso" if m["late"] else "",
                             f"{m['decision_pending']} decisão(ões) pendente(s)" if m["decision_pending"] else "", f"{m['triage_overdue']} triagem(ns) fora da meta" if m["triage_overdue"] else "") if x]
        if not with_pd:
            rows.append({"check": "incidentdesk", "control": "MON-04", "status": "unknown", "detail": "nenhum incidente com dados pessoais", "platform": "ir"})
        else:
            rows.append({"check": "incidentdesk", "control": "MON-04", "status": "fail" if bad04 else "pass",
                         "detail": ("; ".join(bad04)) if bad04 else "comunicações exigidas dentro do prazo e decisões registradas", "platform": "ir"})
    return json.dumps({"collected_at": datetime.now().isoformat(timespec="seconds"), "system": "ir", "note": "Gerado pelo IncidentDesk. Resultado agregado, sem dados de incidentes.",
                       "results": rows}, ensure_ascii=False, indent=2)


def to_feed(desk: Desk) -> List[Dict]:
    """Um evento por incidente em aberto, no formato genérico do Venator e do CorrelAI. Sem título, descrição nem texto livre."""
    now = time.time()
    return [{"ts": now, "source": "incidentdesk", "type": "generic", "ip": "", "severity": SEVERITY_TO_FEED[i["severity"]],
             "message": f"Incidente {i['id']} ({i['category']}) em aberto, status {i['status']}"} for i in desk.store.incidents() if i["status"] != "encerrado"]


CSS = """
:root{color-scheme:dark;--bg:#0b1118;--panel:#121b26;--line:#263a4b;--text:#e6eef5;--muted:#8ba2b4}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.55 "Segoe UI",system-ui,sans-serif}
main{max-width:1060px;margin:0 auto;padding:30px 22px 70px}h1{margin:0;font-size:26px}h2{font-size:17px;margin:28px 0 8px}.sub{color:var(--muted);margin:4px 0 0}
.top{display:flex;gap:12px;flex-wrap:wrap;margin:22px 0}.card{flex:1;min-width:130px;background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px 18px}
.card b{display:block;font-size:30px;line-height:1.1}.card span{color:var(--muted);font-size:13px}
.d{background:var(--panel);border:1px solid var(--line);border-left-width:4px;border-radius:10px;padding:11px 14px;margin:8px 0}
.badge{font-size:11.5px;font-weight:700;border-radius:999px;padding:1px 9px;color:#07121b;white-space:nowrap}.muted{color:var(--muted);font-size:12.5px}
table{width:100%;border-collapse:collapse;background:var(--panel);border:1px solid var(--line)}th{text-align:left;color:var(--muted);font-weight:500;padding:8px 10px;border-bottom:1px solid var(--line)}
td{padding:8px 10px;border-bottom:1px solid var(--line)}.note{color:var(--muted);font-size:12.5px;margin-top:30px;border-top:1px solid var(--line);padding-top:14px}
"""


def render_html(desk: Desk) -> str:
    e = html.escape
    m, problems, now = desk.metrics(), desk.verify(), desk.now()
    ds = desk.all_deadlines()
    open_dl = [d for d in ds if d["status"] in ("vencido", "hoje", "a_vencer")]
    cards = "".join(f"<div class='d' style='border-left-color:{COLOR[d['status']]}'><span class='badge' style='background:{COLOR[d['status']]}'>{e(STATUS_LABEL[d['status']])}</span> "
                    f"<b>{e(d['incident']['id'])}</b> · {e(d['name'])} {'(lei)' if d['legal'] else '(meta interna)'}"
                    f"<div class='muted'>{e(d['incident']['title'])}</div><div class='muted'>Prazo {_fmt(d['due'])} · {e(d['remaining'])}"
                    f"{' · ' + e(d['note']) if d['note'] else ''}</div></div>" for d in open_dl) or "<p class='sub'>Nenhum prazo em aberto.</p>"
    rows = "".join(f"<tr><td><b>{e(i['id'])}</b></td><td>{e(i['title'])}</td><td><span class='badge' style='background:{COLOR[i['severity']]}'>{e(i['severity'])}</span></td>"
                   f"<td>{e(i['status'])}</td><td>{e(i['pd_status'])}</td><td>{e(i['anpd_decision'])}</td></tr>" for i in desk.store.incidents())
    integrity = "<span style='color:#3ddc84'>íntegro</span>" if not problems else f"<span style='color:#ff5c7a'>{len(problems)} problema(s)</span>"
    return f"""<!DOCTYPE html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>IncidentDesk - painel</title><style>{CSS}</style></head><body><main>
<h1>IncidentDesk</h1><p class="sub">Registro de incidentes e relógio de prazos · agora {_fmt(now)} · integridade do registro: {integrity}</p>
<div class="top"><div class="card"><span>Em aberto</span><b>{m['open']}</b></div>
<div class="card"><span>Prazos vencidos</span><b style="color:#ff5c7a">{sum(1 for d in open_dl if d['status'] == 'vencido')}</b></div>
<div class="card"><span>Vencem hoje</span><b style="color:#ff9a45">{sum(1 for d in open_dl if d['status'] == 'hoje')}</b></div>
<div class="card"><span>Decisões pendentes</span><b>{m['decision_pending']}</b></div><div class="card"><span>ANPD no prazo</span><b style="color:#3ddc84">{m['on_time']}/{m['required']}</b></div></div>
<h2>Prazos em aberto</h2>{cards}<h2>Incidentes</h2><table><tr><th>ID</th><th>Título</th><th>Grav.</th><th>Status</th><th>Dados pessoais</th><th>Comunicar ANPD</th></tr>{rows}</table>
<p class="note">Prazo legal: LGPD art. 48 e Res. CD/ANPD 15/2024, em dias úteis (feriados nacionais). A ferramenta calcula e lembra; a decisão e o envio são humanos.
Este painel descreve incidentes reais: confidencial.</p></main></body></html>"""
