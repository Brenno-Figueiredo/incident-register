"""Linha de comando do IncidentDesk."""
from __future__ import annotations

import argparse
import json
import os
import sys

from . import __version__, report
from .calendar import Calendar, load_holidays
from .desk import Desk
from .model import CATEGORIES, DATA_FLAGS, PD_STATUS, SEVERITIES, ValidationError, parse_dt
from .store import Store

DEFAULT_DB = "incidentes.db"


def common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--db", default=DEFAULT_DB, help=f"arquivo do registro (padrão: {DEFAULT_DB})")
    p.add_argument("--now", metavar="'AAAA-MM-DD HH:MM'", help="simula a data e hora atuais (para conferir prazos)")
    p.add_argument("--holidays", metavar="ARQ.txt", help="feriados extras (estaduais, municipais, pontos facultativos), um por linha")
    p.add_argument("--pontos-facultativos", action="store_true", help="trata Carnaval e Corpus Christi como dias não úteis")
    p.add_argument("--actor", default=os.environ.get("USERNAME") or os.environ.get("USER") or "analista", help="quem está registrando")
    p.add_argument("--bcb-hours", type=int, help="prazo INTERNO (em horas) para comunicar o Banco Central em incidente relevante")
    p.add_argument("--triage-hours", type=int, default=24, help="meta interna de triagem, em horas (padrão 24)")
    p.add_argument("--no-color", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="incidentdesk", description="Registro de incidentes de segurança com o relógio dos prazos da LGPD e da ANPD.",
                                 epilog="Calcula e lembra; a decisão e o envio das comunicações são humanos. NÃO registre dados pessoais dos titulares.")
    sub = ap.add_subparsers(dest="cmd")

    def add(name, help_):
        sp = sub.add_parser(name, help=help_)
        common(sp)
        return sp

    add("init", "cria o registro (arquivo)")
    n = add("new", "registra um incidente")
    n.add_argument("--title")
    n.add_argument("--description", default="")
    n.add_argument("--category", default="outro", help="/".join(CATEGORIES))
    n.add_argument("--severity", default="media", help="/".join(SEVERITIES))
    n.add_argument("--detected", help="quando foi detectado (padrão: agora)")
    n.add_argument("--occurred", help="quando ocorreu, se souber")
    n.add_argument("--pd", default="investigando", help="dados pessoais afetados? " + "/".join(PD_STATUS))
    n.add_argument("--aware-at", help="quando o controlador soube que dados pessoais foram afetados (começa o prazo)")
    n.add_argument("--data", default="", help="tipos de dados: " + ",".join(DATA_FLAGS))
    n.add_argument("--titulares", help="número estimado de titulares")
    n.add_argument("--significant", default="avaliando", help="afeta significativamente direitos dos titulares? sim/nao/avaliando")
    n.add_argument("--role", default="controlador", help="controlador/operador")
    n.add_argument("--small", action="store_true", help="agente de tratamento de pequeno porte (prazo em dobro)")
    n.add_argument("--bcb", default="avaliando", help="incidente relevante para o Banco Central? sim/nao/avaliando")
    n.add_argument("--systems", default="")
    n.add_argument("--vendor", default="")
    n.add_argument("--owner", default="")
    n.add_argument("-i", "--interactive", action="store_true", help="pergunta um campo por vez")
    u = add("update", "atualiza um incidente")
    u.add_argument("id")
    for flag in ("title", "description", "category", "severity", "status", "pd", "aware-at", "data", "titulares", "significant", "role", "small", "bcb", "systems",
                 "vendor", "owner", "occurred", "root-cause", "lessons"):
        u.add_argument(f"--{flag}")
    u.add_argument("--reason", default="", help="motivo (obrigatório ao mudar a data de conhecimento)")
    nt = add("note", "anota na linha do tempo")
    nt.add_argument("id")
    nt.add_argument("text")
    nt.add_argument("--kind", default="nota", help="nota/contencao/mitigacao/evidencia/decisao")
    cm = add("comm", "registra uma comunicação enviada")
    cm.add_argument("id")
    cm.add_argument("--to", required=True, help="anpd/titulares/bcb/controlador/cliente/outro")
    cm.add_argument("--kind", default="preliminar", help="preliminar/complementar/declaracao_titulares/outra")
    cm.add_argument("--at", help="quando foi enviada (padrão: agora)")
    cm.add_argument("--ref", default="", help="número do protocolo")
    cm.add_argument("--notes", default="")
    dc = add("decide", "registra a decisão de comunicar (ou não) a ANPD, com justificativa")
    dc.add_argument("id")
    dc.add_argument("--anpd", required=True, help="sim/nao")
    dc.add_argument("--why", required=True, help="justificativa (obrigatória)")
    cl = add("close", "encerra um incidente (exige a causa raiz)")
    cl.add_argument("id")
    cl.add_argument("--root-cause", default="")
    cl.add_argument("--lessons", default="")
    cl.add_argument("--at")
    cl.add_argument("--force", action="store_true")
    ls = add("list", "lista os incidentes")
    ls.add_argument("--all", action="store_true", help="inclui os encerrados")
    sh = add("show", "mostra o dossiê de um incidente")
    sh.add_argument("id")
    d = add("deadlines", "mostra o relógio dos prazos")
    d.add_argument("--all", action="store_true", help="inclui os já cumpridos")
    d.add_argument("--fail-on-overdue", action="store_true", help="código de saída 1 se algum prazo LEGAL estiver vencido")
    a = add("assess", "avalia se há risco ou dano relevante (art. 5º)")
    a.add_argument("id")
    dr = add("draft", "gera o rascunho da comunicação")
    dr.add_argument("id")
    dr.add_argument("--kind", default="anpd", help="anpd/titulares")
    add("metrics", "mostra as métricas")
    vf = add("verify", "confere a integridade da trilha de auditoria")
    vf.add_argument("--anchor", metavar="HASH", help="hash final guardado em outro lugar: prova que o histórico até aquele ponto não foi reescrito")
    ex = add("export", "exporta o registro (CSV)")
    ex.add_argument("--csv", required=True)
    rp = add("report", "painel HTML")
    rp.add_argument("--html", required=True)
    cmap = add("compliancemap", "evidência agregada para o ComplianceMap (--auto)")
    cmap.add_argument("file")
    fd = add("feed", "eventos para o Venator e o CorrelAI")
    fd.add_argument("file")
    dm = sub.add_parser("demo", help="mostra o relógio com incidentes FICTÍCIOS (relógio simulado: 22/10/2026 10:00)")
    dm.add_argument("--html")
    dm.add_argument("--no-color", action="store_true")
    dm.add_argument("--holidays")
    wd = sub.add_parser("workdays", help="calcula N dias úteis a partir de uma data (confere a contagem)")
    wd.add_argument("--from", dest="start", required=True)
    wd.add_argument("--n", type=int, default=3)
    wd.add_argument("--holidays")
    wd.add_argument("--pontos-facultativos", action="store_true")
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return ap


def _calendar(a) -> Calendar:
    extra = load_holidays(a.holidays) if getattr(a, "holidays", None) else None
    return Calendar(extra, getattr(a, "pontos_facultativos", False))


def make_desk(a, must_exist: bool = True) -> Desk:
    if must_exist and a.db != ":memory:" and not os.path.exists(a.db):
        raise ValidationError(f"registro '{a.db}' não encontrado. Crie-o com: init")
    cfg = {"triage_hours": a.triage_hours, "bcb_hours": a.bcb_hours}
    return Desk(Store(a.db), _calendar(a), cfg, now=parse_dt(a.now, "--now") if a.now else None, actor=a.actor)


def _warn(desk: Desk) -> None:
    for w in desk.warnings:
        print(f"Aviso: {w}", file=sys.stderr)


def _ask(prompt: str, default: str = "") -> str:
    answer = input(f"{prompt}{f' [{default}]' if default else ''}: ").strip()
    return answer or default


def _interactive(a) -> None:
    print("Novo incidente (Enter aceita o valor entre colchetes). NÃO digite dados pessoais dos titulares.\n")
    a.title = _ask("Título")
    a.description = _ask("Descrição (curta)")
    a.category = _ask(f"Categoria ({'/'.join(CATEGORIES)})", a.category)
    a.severity = _ask(f"Gravidade ({'/'.join(SEVERITIES)})", a.severity)
    a.detected = _ask("Quando foi detectado (AAAA-MM-DD HH:MM; Enter = agora)") or None
    a.pd = _ask("Dados pessoais foram afetados? (sim/nao/investigando)", a.pd)
    if a.pd == "sim":
        a.aware_at = _ask("Quando soube que dados pessoais foram afetados (Enter = momento da detecção)") or None
        a.data = _ask("Tipos de dados (" + ",".join(DATA_FLAGS) + ")")
        a.titulares = _ask("Número estimado de titulares") or None
        a.significant = _ask("Afeta significativamente os direitos dos titulares? (sim/nao/avaliando)", a.significant)
    a.role = _ask("Papel (controlador/operador)", a.role)
    a.owner = _ask("Responsável")


def cmd_new(a) -> int:
    if a.interactive:
        _interactive(a)
    desk = make_desk(a)
    iid = desk.new(a.title or "", a.description, a.category, a.severity, a.detected, a.occurred, a.pd, a.aware_at, a.data, a.titulares, a.significant, a.role,
                   a.small, a.bcb, a.systems, a.vendor, a.owner)
    _warn(desk)
    print(f"Incidente registrado: {iid}")
    for d in desk.deadlines(iid):
        if d["status"] not in ("cumprido",):
            print(f"  prazo: {d['name']} até {d['due']:%d/%m/%Y %H:%M}" + (f" ({d['remaining']})" if d["remaining"] else ""))
    if a.pd == "investigando":
        print("  Lembrete: o prazo legal só começa quando você confirmar que dados pessoais foram afetados (update --pd sim).")
    return 0


def cmd_update(a) -> int:
    desk = make_desk(a)
    mapping = {"title": "title", "description": "description", "category": "category", "severity": "severity", "status": "status", "pd": "pd_status",
               "aware_at": "pd_aware_at", "data": "data_flags", "titulares": "affected_count", "significant": "significant_impact", "role": "role", "small": "small_agent",
               "bcb": "bcb_relevant", "systems": "systems", "vendor": "vendor", "owner": "owner", "occurred": "occurred_at", "root_cause": "root_cause", "lessons": "lessons"}
    changes = {dest: getattr(a, src) for src, dest in mapping.items() if getattr(a, src, None) is not None}
    diff = desk.update(a.id, a.reason, **changes)
    _warn(desk)
    print("Atualizado: " + (", ".join(diff) if diff else "nada mudou"))
    return 0


def cmd_note(a) -> int:
    desk = make_desk(a)
    desk.note(a.id, a.text, a.kind)
    _warn(desk)
    print("Anotação registrada.")
    return 0


def cmd_comm(a) -> int:
    desk = make_desk(a)
    desk.comm(a.id, a.to, a.kind, a.at, a.ref, a.notes)
    _warn(desk)
    print("Comunicação registrada.")
    for d in desk.deadlines(a.id):
        if d["done_at"]:
            print(f"  {d['name']}: {'dentro do prazo' if d['status'] == 'cumprido' else 'COM ATRASO'}")
    return 0


def cmd_decide(a) -> int:
    desk = make_desk(a)
    desk.decide(a.id, a.anpd, a.why)
    _warn(desk)
    print("Decisão registrada.")
    return 0


def cmd_close(a) -> int:
    desk = make_desk(a)
    desk.close(a.id, a.root_cause, a.lessons, a.at, a.force)
    _warn(desk)
    print("Incidente encerrado. O registro deve ser guardado por 5 anos.")
    return 0


def cmd_list(a) -> int:
    print(report.render_list(make_desk(a), a.all))
    return 0


def cmd_show(a) -> int:
    print(report.render_incident(make_desk(a), a.id))
    return 0


def cmd_deadlines(a) -> int:
    desk = make_desk(a)
    print(report.render_deadlines(desk, not a.no_color and sys.stdout.isatty(), a.all))
    if a.fail_on_overdue and any(d["legal"] and d["status"] == "vencido" for d in desk.all_deadlines()):
        return 1
    return 0


def cmd_assess(a) -> int:
    r = make_desk(a).assessment(a.id)
    print(r["summary"])
    if r["criteria"]:
        print("Critérios presentes: " + "; ".join(r["criteria"]))
    print("\nÉ uma sugestão. A decisão é do encarregado e do jurídico, e deve ser registrada com justificativa (decide).")
    return 0


def cmd_draft(a) -> int:
    print(make_desk(a).draft(a.id, a.kind))
    return 0


def cmd_metrics(a) -> int:
    print(report.render_metrics(make_desk(a)))
    return 0


def cmd_verify(a) -> int:
    desk = make_desk(a)
    problems = desk.verify()
    if a.anchor and not desk.store.has_hash(a.anchor):
        problems.append("a âncora informada não existe na cadeia: o histórico foi reescrito (ou a âncora é de outro registro)")
    if not problems:
        print("Registro íntegro: a cadeia de hashes confere e nenhum dado foi alterado fora do programa.")
        if a.anchor:
            print("Âncora confere: o histórico até aquele ponto não foi reescrito.")
        print(f"\nHash final da cadeia (anote e guarde FORA deste computador): {desk.store.head_hash()}")
        print("Depois, confira com:  verify --anchor <hash>. Isso detecta até quem recalcular a cadeia inteira.")
        return 0
    print(f"ATENÇÃO: {len(problems)} problema(s) de integridade:")
    for p in problems:
        print(f"  - {p}")
    return 1


def _write(path: str, text: str, label: str, bom: bool = False) -> None:
    with open(path, "w", encoding="utf-8-sig" if bom else "utf-8", newline="") as f:
        f.write(text)
    print(f"{label} salvo em: {path}")


def cmd_export(a) -> int:
    _write(a.csv, report.register_csv(make_desk(a)), "Registro", bom=True)
    return 0


def cmd_report(a) -> int:
    _write(a.html, report.render_html(make_desk(a)), "Painel")
    return 0


def cmd_compliancemap(a) -> int:
    _write(a.file, report.to_compliancemap(make_desk(a)), "Evidência")
    return 0


def cmd_feed(a) -> int:
    events = report.to_feed(make_desk(a))
    with open(a.file, "w", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    print(f"{len(events)} evento(s) salvos em: {a.file}")
    return 0


def cmd_init(a) -> int:
    if os.path.exists(a.db):
        raise ValidationError(f"'{a.db}' já existe. O registro não é recriado nem apagado (guarda de 5 anos)")
    Store(a.db).close()
    print(f"Registro criado: {a.db}\nGuarde esse arquivo com backup e NÃO o envie ao GitHub (o .gitignore já bloqueia).")
    return 0


def cmd_demo(a) -> int:
    from .samples import build
    desk = build(":memory:", _calendar(a))
    color = not a.no_color and sys.stdout.isatty()
    print("DEMONSTRAÇÃO com incidentes FICTÍCIOS (relógio simulado: 22/10/2026 10:00, quinta-feira)\n")
    print(report.render_deadlines(desk, color))
    print("\n" + report.render_metrics(desk))
    if a.html:
        _write(a.html, report.render_html(desk), "Painel")
    return 0


def cmd_workdays(a) -> int:
    start = parse_dt(a.start, "data")
    cal = _calendar(a)
    end = cal.add_business_days(start.date(), a.n)
    print(f"{a.n} dia(s) útil(eis) depois de {start:%d/%m/%Y} ({start:%A}) → {end:%d/%m/%Y}. O dia de início não conta; o prazo vai até 23:59 do último dia.")
    return 0


COMMANDS = {"init": cmd_init, "new": cmd_new, "update": cmd_update, "note": cmd_note, "comm": cmd_comm, "decide": cmd_decide, "close": cmd_close, "list": cmd_list,
            "show": cmd_show, "deadlines": cmd_deadlines, "assess": cmd_assess, "draft": cmd_draft, "metrics": cmd_metrics, "verify": cmd_verify, "export": cmd_export,
            "report": cmd_report, "compliancemap": cmd_compliancemap, "feed": cmd_feed, "demo": cmd_demo, "workdays": cmd_workdays}


def main(argv=None) -> int:
    ap = build_parser()
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 0
    try:
        return COMMANDS[a.cmd](a)
    except (ValidationError, ValueError, OSError) as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 2
