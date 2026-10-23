import contextlib
import csv
import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import date, datetime
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from incidentdesk import deadlines as dl, report, triage  # noqa: E402
from incidentdesk.calendar import Calendar, easter, load_holidays, national_holidays  # noqa: E402
from incidentdesk.cli import main  # noqa: E402
from incidentdesk.desk import Desk  # noqa: E402
from incidentdesk.model import PiiError, ValidationError, check_text, parse_dt, parse_flags, scan_pii, choice  # noqa: E402
from incidentdesk.samples import DEMO_NOW, build  # noqa: E402
from incidentdesk.store import STATE_FIELDS, Store, state_hash  # noqa: E402

NOW = datetime(2026, 10, 22, 10, 0)
VALID_CPF = "529.982.247-25"                                   # CPF de teste com dígitos verificadores corretos
VALID_CARD = "4111 1111 1111 1111"                             # número de teste que passa em Luhn


def make(now=NOW, **cfg) -> Desk:
    return Desk(Store(":memory:"), Calendar(), cfg, now=now, actor="teste")


def pd_incident(desk, **kw):
    base = dict(title="Incidente de teste", category="vazamento", severity="alta", detected_at="2026-10-19 08:30", pd_status="sim", pd_aware_at="2026-10-19 09:00",
                data_flags="financeiros", affected_count=10, significant_impact="sim")
    base.update(kw)
    return desk.new(**base)


def dl_of(desk, iid, key):
    return next((d for d in desk.deadlines(iid) if d["key"] == key), None)


class CalendarTests(unittest.TestCase):
    def test_easter_known_dates(self):
        for year, expected in ((2024, date(2024, 3, 31)), (2025, date(2025, 4, 20)), (2026, date(2026, 4, 5)), (2027, date(2027, 3, 28)), (2030, date(2030, 4, 21))):
            self.assertEqual(easter(year), expected, year)

    def test_national_holidays(self):
        h = national_holidays(2026)
        self.assertEqual(len(h), 10)
        self.assertIn(date(2026, 4, 3), h)                                 # Sexta-feira Santa
        self.assertIn(date(2026, 10, 12), h)
        self.assertIn(date(2024, 11, 20), national_holidays(2024))         # Consciência Negra: nacional a partir de 2024
        self.assertNotIn(date(2023, 11, 20), national_holidays(2023))
        optional = national_holidays(2026, optional_points=True)
        self.assertEqual({date(2026, 2, 16), date(2026, 2, 17), date(2026, 6, 4)} - set(optional), set())
        self.assertEqual(len(optional) - len(h), 3)

    def test_business_days(self):
        c = Calendar()
        self.assertFalse(c.is_business_day(date(2026, 10, 24)))            # sábado
        self.assertFalse(c.is_business_day(date(2026, 10, 12)))            # feriado (segunda)
        self.assertTrue(c.is_business_day(date(2026, 10, 13)))

    def test_add_business_days(self):
        c = Calendar()
        self.assertEqual(c.add_business_days(date(2026, 10, 19), 3), date(2026, 10, 22))     # segunda + 3
        self.assertEqual(c.add_business_days(date(2026, 10, 14), 3), date(2026, 10, 19))     # atravessa o fim de semana
        self.assertEqual(c.add_business_days(date(2026, 10, 8), 3), date(2026, 10, 14))      # atravessa o feriado de 12/10
        self.assertEqual(c.add_business_days(date(2026, 10, 24), 1), date(2026, 10, 26))     # começa no sábado
        self.assertEqual(c.add_business_days(date(2026, 10, 23), 1), date(2026, 10, 26))     # começa na sexta
        self.assertEqual(c.add_business_days(date(2026, 10, 19), 0), date(2026, 10, 19))
        self.assertEqual(c.add_business_days(date(2026, 10, 13), 20), date(2026, 11, 11))    # 20 dias úteis, com o feriado de 02/11 no meio

    def test_business_days_between(self):
        c = Calendar()
        self.assertEqual(c.business_days_between(date(2026, 10, 19), date(2026, 10, 22)), 3)
        self.assertEqual(c.business_days_between(date(2026, 10, 22), date(2026, 10, 19)), -3)
        self.assertEqual(c.business_days_between(date(2026, 10, 22), date(2026, 10, 22)), 0)
        self.assertEqual(c.business_days_between(date(2026, 10, 23), date(2026, 10, 26)), 1)

    def test_extra_holidays_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "h.txt")
            with open(path, "w", encoding="utf-8") as f:
                f.write("# feriados da cidade\n2026-10-20 Aniversário da cidade\n21/10/2026\n\n")
            extra = load_holidays(path)
            self.assertEqual(set(extra), {date(2026, 10, 20), date(2026, 10, 21)})
            c = Calendar(extra)
            self.assertEqual(c.add_business_days(date(2026, 10, 19), 3), date(2026, 10, 26))   # 20 e 21 não contam
            with open(path, "w", encoding="utf-8") as f:
                f.write("amanhã\n")
            with self.assertRaises(ValueError):
                load_holidays(path)


class ModelTests(unittest.TestCase):
    def test_parse_dt(self):
        for text in ("2026-10-22 14:30", "22/10/2026 14:30", "2026-10-22T14:30"):
            self.assertEqual(parse_dt(text), datetime(2026, 10, 22, 14, 30))
        self.assertEqual(parse_dt("22/10/2026"), datetime(2026, 10, 22))
        self.assertIsNone(parse_dt(""))
        with self.assertRaises(ValidationError):
            parse_dt("ontem")

    def test_choice_and_flags(self):
        self.assertEqual(choice("Média", ("baixa", "media"), "gravidade"), "media")
        self.assertEqual(choice("  Acesso Indevido ", ("acesso_indevido",), "x"), "acesso_indevido")
        with self.assertRaises(ValidationError):
            choice("enorme", ("baixa",), "gravidade")
        self.assertEqual(parse_flags("financeiros, sensiveis"), "financeiros,sensiveis")
        with self.assertRaises(ValidationError):
            parse_flags("fotos")

    def test_pii_scan_finds_real_looking_data_only(self):
        self.assertEqual(scan_pii(f"titular {VALID_CPF} afetado")["cpf"], 1)
        self.assertEqual(scan_pii("cpf 52998224725")["cpf"], 1)
        self.assertEqual(scan_pii("123.456.789-00")["cpf"], 0)                      # dígitos verificadores errados
        self.assertEqual(scan_pii(f"cartão {VALID_CARD}")["cartao"], 1)
        self.assertEqual(scan_pii("1234 5678 9012 3456")["cartao"], 0)              # não passa em Luhn
        for harmless in ("INC-2026-0001", "2026-10-22 14:30", "protocolo 20261022", "12000 titulares", "Servidor 10.0.0.15"):
            self.assertEqual(sum(scan_pii(harmless).values()), 0, harmless)
        self.assertEqual(scan_pii("fulano@exemplo.com.br")["email"], 1)
        self.assertEqual(scan_pii("ligar para (11) 91234-5678")["telefone"], 1)

    def test_check_text_blocks_cpf_and_card_and_warns_on_email(self):
        with self.assertRaises(PiiError) as ctx:
            check_text(f"vazou o CPF {VALID_CPF}", "título")
        self.assertIn("CPF", str(ctx.exception))
        with self.assertRaises(PiiError):
            check_text(f"cartão {VALID_CARD}")
        self.assertEqual(len(check_text("falar com fulano@exemplo.com.br")), 1)
        self.assertEqual(check_text("sem dados pessoais"), [])


class StoreTests(unittest.TestCase):
    def test_ids_and_state_hash(self):
        desk = make()
        a, b = desk.new("Um"), desk.new("Dois")
        self.assertEqual((a, b), ("INC-2026-0001", "INC-2026-0002"))
        inc = desk.store.incident(a)
        self.assertEqual(inc["state_hash"], state_hash({f: inc[f] for f in STATE_FIELDS}))
        self.assertEqual(desk.store.update(a, {"title": "Um"}, NOW, "t"), {})            # sem mudança: nada gravado
        self.assertEqual(len(desk.store.events(a)), 1)

    def test_store_has_no_delete(self):
        for name in ("delete", "remove", "purge", "drop"):
            self.assertFalse(any(name in n.lower() for n in dir(Store) if not n.startswith("_")))

    def test_verify_ok_after_legit_operations(self):
        desk = make()
        iid = pd_incident(desk)
        desk.note(iid, "Servidor isolado.", "contencao")
        desk.decide(iid, "sim", "Dados financeiros e impacto significativo para os titulares.")
        desk.comm(iid, "anpd", "preliminar", "2026-10-20 09:00", ref="PROT-1")
        desk.update(iid, status="contido")
        self.assertEqual(desk.verify(), [])

    def _db(self):
        path = os.path.join(tempfile.mkdtemp(), "t.db")
        desk = Desk(Store(path), now=NOW)
        iid = pd_incident(desk)
        desk.note(iid, "Primeira nota.", "nota")
        desk.comm(iid, "anpd", "preliminar", "2026-10-20 09:00", ref="PROT-1")
        desk.store.close()
        return path, iid

    def test_tampering_with_an_event_is_detected(self):
        path, _ = self._db()
        con = sqlite3.connect(path)
        con.execute("UPDATE events SET payload = replace(payload, 'Primeira nota.', 'Nota reescrita.') WHERE kind='note'")
        con.commit()
        con.close()
        problems = Store(path).verify()
        self.assertTrue(any("alterado" in p for p in problems), problems)

    def test_deleting_an_event_breaks_the_chain(self):
        path, _ = self._db()
        con = sqlite3.connect(path)
        con.execute("DELETE FROM events WHERE kind='note'")
        con.commit()
        con.close()
        self.assertTrue(any("cadeia" in p for p in Store(path).verify()))

    def test_editing_the_incident_row_directly_is_detected(self):
        path, iid = self._db()
        con = sqlite3.connect(path)
        con.execute("UPDATE incidents SET pd_aware_at='2026-10-21T09:00' WHERE id=?", (iid,))       # tentar "ganhar" dias de prazo
        con.commit()
        con.close()
        self.assertTrue(any("fora do programa" in p for p in Store(path).verify()))

    def test_communication_rows_are_protected_too(self):
        path, iid = self._db()
        con = sqlite3.connect(path)
        con.execute("UPDATE comms SET sent_at='2026-10-19T09:00' WHERE incident_id=?", (iid,))      # tentar "antecipar" o envio
        con.commit()
        con.close()
        self.assertTrue(any("alterada fora do programa" in p for p in Store(path).verify()))
        path, iid = self._db()
        con = sqlite3.connect(path)
        con.execute("DELETE FROM comms")
        con.commit()
        con.close()
        self.assertTrue(any("removida" in p for p in Store(path).verify()))
        path, iid = self._db()
        con = sqlite3.connect(path)
        con.execute("INSERT INTO comms(incident_id, dest, kind, sent_at, ref, notes) VALUES (?, 'anpd', 'preliminar', '2026-10-19T10:00', 'FALSO', '')", (iid,))
        con.commit()
        con.close()
        self.assertTrue(any("não na trilha" in p for p in Store(path).verify()))


class AnchorTests(unittest.TestCase):
    def _forge(self, path):
        """Falsificador cuidadoso: troca o texto de uma nota E recalcula toda a cadeia de hashes."""
        from incidentdesk.store import event_hash
        con = sqlite3.connect(path)
        con.row_factory = sqlite3.Row
        rows = con.execute("SELECT * FROM events ORDER BY id").fetchall()
        prev = "0" * 64
        for r in rows:
            payload = r["payload"].replace("Primeira nota.", "Nota reescrita.")
            h = event_hash(prev, r["ts"], r["actor"], r["kind"], r["incident_id"], payload)
            con.execute("UPDATE events SET payload=?, prev_hash=?, hash=? WHERE id=?", (payload, prev, h, r["id"]))
            prev = h
        con.commit()
        con.close()

    def _db(self):
        path = os.path.join(tempfile.mkdtemp(), "t.db")
        desk = Desk(Store(path), now=NOW)
        iid = pd_incident(desk)
        desk.note(iid, "Primeira nota.", "nota")
        anchor = desk.store.head_hash()
        desk.store.close()
        return path, anchor

    def test_head_hash_changes_with_each_event_and_the_anchor_is_found(self):
        desk = make()
        self.assertEqual(desk.store.head_hash(), "0" * 64)
        iid = desk.new("X")
        first = desk.store.head_hash()
        desk.note(iid, "Mais uma.", "nota")
        self.assertNotEqual(desk.store.head_hash(), first)
        self.assertTrue(desk.store.has_hash(first))
        self.assertTrue(desk.store.has_hash(first.upper()))
        self.assertFalse(desk.store.has_hash("f" * 64))

    def test_a_forger_who_recomputes_the_whole_chain_passes_verify_but_not_the_anchor(self):
        path, anchor = self._db()
        self._forge(path)
        store = Store(path)
        self.assertEqual(store.verify(), [])                          # a cadeia recalculada é consistente: o verify sozinho não pega
        self.assertFalse(store.has_hash(anchor))                      # mas a âncora guardada fora não existe mais
        store.close()

    def test_cli_verify_prints_the_anchor_and_checks_it(self):
        path, anchor = self._db()

        def run(*args):
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = main(list(args) + ["--db", path, "--now", "2026-10-22 10:00"])
            return code, out.getvalue()

        code, out = run("verify")
        self.assertEqual(code, 0)
        self.assertIn(anchor, out)                                    # mostra o hash para o usuário guardar
        code, out = run("verify", "--anchor", anchor)
        self.assertEqual(code, 0)
        self.assertIn("Âncora confere", out)
        self._forge(path)
        code, out = run("verify", "--anchor", anchor)
        self.assertEqual(code, 1)
        self.assertIn("reescrito", out)


class DeadlineTests(unittest.TestCase):
    def test_three_business_days_and_status_over_time(self):
        for now, status in ((datetime(2026, 10, 20, 9, 0), "a_vencer"), (datetime(2026, 10, 22, 10, 0), "hoje"), (datetime(2026, 10, 22, 23, 59), "hoje"),
                            (datetime(2026, 10, 23, 0, 0), "vencido")):
            desk = make(now)
            d = dl_of(desk, pd_incident(desk, detected_at="2026-10-19 08:30"), "anpd")
            self.assertEqual(d["due"], datetime(2026, 10, 22, 23, 59))
            self.assertEqual(d["status"], status, now)

    def test_clock_starts_at_knowledge_not_at_detection(self):
        desk = make()
        iid = pd_incident(desk, detected_at="2026-10-15 08:00", pd_aware_at="2026-10-19 09:00")
        self.assertEqual(dl_of(desk, iid, "anpd")["due"], datetime(2026, 10, 22, 23, 59))

    def test_small_agent_doubles_the_deadline(self):
        desk = make()
        d = dl_of(desk, pd_incident(desk, small_agent=True), "anpd")
        self.assertEqual(d["due"], datetime(2026, 10, 27, 23, 59))                  # 6 dias úteis
        self.assertIn("pequeno porte", d["note"])

    def test_holiday_inside_the_window(self):
        desk = make()
        iid = pd_incident(desk, detected_at="2026-10-08 08:00", pd_aware_at="2026-10-08 11:00")
        self.assertEqual(dl_of(desk, iid, "anpd")["due"], datetime(2026, 10, 14, 23, 59))      # 12/10 é feriado

    def test_no_legal_deadline_until_personal_data_is_confirmed(self):
        desk = make()
        iid = desk.new("Em investigação", detected_at="2026-10-21 08:00")
        keys = {d["key"] for d in desk.deadlines(iid)}
        self.assertEqual(keys, {"triagem"})
        iid2 = desk.new("Sem dados pessoais", pd_status="nao")
        self.assertNotIn("anpd", {d["key"] for d in desk.deadlines(iid2)})

    def test_decision_not_to_communicate_removes_the_legal_deadlines(self):
        desk = make()
        iid = pd_incident(desk)
        self.assertIn("provisório", dl_of(desk, iid, "anpd")["note"])
        desk.decide(iid, "nao", "Sem critérios do art. 5º e impacto não significativo.")
        self.assertEqual([d["key"] for d in desk.deadlines(iid) if d["legal"]], [])

    def test_communication_on_time_and_late(self):
        desk = make()
        iid = pd_incident(desk)
        desk.comm(iid, "anpd", "preliminar", "2026-10-21 16:00")
        self.assertEqual(dl_of(desk, iid, "anpd")["status"], "cumprido")
        desk2 = make(datetime(2026, 10, 23, 12, 0))                       # já passou do prazo (22/10 23:59)
        iid2 = pd_incident(desk2)
        desk2.comm(iid2, "anpd", "preliminar", "2026-10-23 09:00")
        d = dl_of(desk2, iid2, "anpd")
        self.assertEqual(d["status"], "cumprido_atraso")
        self.assertEqual(d["remaining"], "")

    def test_complement_is_twenty_business_days_after_the_preliminary(self):
        desk = make()
        iid = pd_incident(desk)
        self.assertIsNone(dl_of(desk, iid, "complemento"))
        desk.comm(iid, "anpd", "preliminar", "2026-10-13 15:00")
        self.assertEqual(dl_of(desk, iid, "complemento")["due"], datetime(2026, 11, 11, 23, 59))
        self.assertEqual(dl_of(desk, iid, "complemento")["status"], "a_vencer")
        desk.comm(iid, "anpd", "complementar", "2026-10-21 10:00")
        self.assertEqual(dl_of(desk, iid, "complemento")["status"], "cumprido")

    def test_declaration_to_anpd_follows_the_titulares_deadline(self):
        desk = make()
        d = dl_of(desk, pd_incident(desk), "declaracao")
        self.assertEqual(d["due"], datetime(2026, 10, 27, 23, 59))                  # 22/10 + 3 dias úteis
        self.assertIn("confirme", d["note"])

    def test_operator_must_notify_the_controller(self):
        desk = make()
        iid = pd_incident(desk, role="operador")
        keys = {d["key"] for d in desk.deadlines(iid)}
        self.assertIn("controlador", keys)
        self.assertNotIn("anpd", keys)
        self.assertEqual(dl_of(desk, iid, "controlador")["due"], datetime(2026, 10, 20, 9, 0))      # 24 h depois de 19/10 09:00

    def test_internal_triage_target(self):
        desk = make()
        iid = desk.new("Notebook", detected_at="2026-10-21 08:00")
        self.assertEqual(dl_of(desk, iid, "triagem")["status"], "vencido")           # 24 h passaram às 08:00 de hoje
        self.assertFalse(dl_of(desk, iid, "triagem")["legal"])
        desk72 = make(triage_hours=72)
        self.assertEqual(dl_of(desk72, desk72.new("Notebook", detected_at="2026-10-21 08:00"), "triagem")["status"], "a_vencer")
        desk.update(iid, pd_status="nao")
        self.assertEqual(dl_of(desk, iid, "triagem")["status"], "cumprido")

    def test_bcb_internal_deadline_is_opt_in(self):
        desk = make()
        iid = desk.new("Incidente relevante", detected_at="2026-10-22 08:00", bcb_relevant="sim")
        self.assertIsNone(dl_of(desk, iid, "bcb"))
        desk = make(bcb_hours=6)
        iid = desk.new("Incidente relevante", detected_at="2026-10-22 08:00", bcb_relevant="sim")
        self.assertEqual(dl_of(desk, iid, "bcb")["due"], datetime(2026, 10, 22, 14, 0))
        desk.comm(iid, "bcb", "preliminar", "2026-10-22 09:30")
        self.assertEqual(dl_of(desk, iid, "bcb")["status"], "cumprido")

    def test_retention_five_years(self):
        self.assertEqual(dl.retain_until({"closed_at": "2026-10-06T09:00", "detected_at": "2026-10-05T11:00"}), datetime(2031, 10, 6, 9, 0))
        self.assertEqual(dl.retain_until({"closed_at": "", "detected_at": "2024-02-29T10:00"}, 1), datetime(2025, 2, 28, 10, 0))
        self.assertIsNone(dl.retain_until({"closed_at": "", "detected_at": ""}))


class TriageTests(unittest.TestCase):
    def inc(self, **kw):
        base = {"pd_status": "sim", "significant_impact": "sim", "data_flags": "financeiros"}
        base.update(kw)
        return base

    def test_assessment_cases(self):
        self.assertFalse(triage.assess(self.inc(pd_status="nao"))["probable"])
        self.assertIsNone(triage.assess(self.inc(pd_status="investigando"))["probable"])
        self.assertIsNone(triage.assess(self.inc(significant_impact="avaliando"))["probable"])
        self.assertFalse(triage.assess(self.inc(significant_impact="nao"))["probable"])
        self.assertTrue(triage.assess(self.inc())["probable"])
        no_criteria = triage.assess(self.inc(data_flags=""))
        self.assertFalse(no_criteria["probable"])
        self.assertIn("cumulativos", no_criteria["summary"])
        self.assertEqual(len(triage.assess(self.inc(data_flags="sensiveis,larga_escala"))["criteria"]), 2)

    def test_drafts(self):
        desk = make()
        iid = pd_incident(desk, data_flags="autenticacao,financeiros", vendor="Fornecedor X")
        desk.note(iid, "Credenciais redefinidas.", "contencao")
        text = desk.draft(iid, "anpd")
        for expected in ("art. 48, § 1º", "I - Natureza", "VI - Medidas", "[PREENCHER]", "Credenciais redefinidas.", "Fornecedor X", "19/10/2026 09:00", "rascunho"):
            self.assertIn(expected, text)
        self.assertIn("Não se aplica", text)
        late = make(datetime(2026, 10, 24, 10, 0))
        text_late = late.draft(pd_incident(late), "anpd")
        self.assertIn("FORA do prazo", text_late)
        titulares = desk.draft(iid, "titulares")
        self.assertIn("senhas", titulares)
        self.assertIn("movimentações", titulares)
        self.assertEqual(sum(scan_pii(text + titulares).values()), 0)


class DeskTests(unittest.TestCase):
    def test_new_validations(self):
        desk = make()
        with self.assertRaises(ValidationError):
            desk.new("  ")
        with self.assertRaises(ValidationError):
            desk.new("Futuro", detected_at="2026-12-01 10:00")
        with self.assertRaises(ValidationError):
            desk.new("Categoria", category="alienígena")
        with self.assertRaises(ValidationError):
            desk.new("Titulares", affected_count="muitos")
        with self.assertRaises(ValidationError):
            desk.new("Titulares", affected_count=-3)
        with self.assertRaises(PiiError):
            desk.new(f"Vazou o CPF {VALID_CPF}")
        with self.assertRaises(PiiError):
            desk.new("Ok", description=f"cartão {VALID_CARD}")
        self.assertEqual(desk.store.incidents(), [])                       # nada foi gravado nos casos inválidos

    def test_warnings_for_email_and_phone(self):
        desk = make()
        desk.new("Contato", description="Avisar fulano@exemplo.com.br")
        self.assertEqual(len(desk.warnings), 1)

    def test_defaults_for_personal_data_status(self):
        desk = make()
        sim = desk.store.incident(desk.new("A", pd_status="sim", detected_at="2026-10-21 09:00"))
        self.assertEqual((sim["pd_aware_at"], sim["anpd_decision"]), ("2026-10-21T09:00", "pendente"))
        nao = desk.store.incident(desk.new("B", pd_status="nao"))
        self.assertEqual((nao["anpd_decision"], nao["pd_aware_at"]), ("nao", ""))
        self.assertIn("Sem dados pessoais", nao["anpd_justification"])
        inv = desk.store.incident(desk.new("C"))
        self.assertEqual((inv["pd_status"], inv["pd_aware_at"]), ("investigando", ""))

    def test_detection_time_is_immutable(self):
        desk = make()
        iid = desk.new("X")
        with self.assertRaises(ValidationError) as ctx:
            desk.update(iid, detected_at="2026-10-22 09:00")
        self.assertIn("detecção", str(ctx.exception))
        with self.assertRaises(ValidationError):
            desk.update(iid, anpd_decision="nao")
        with self.assertRaises(ValidationError):
            desk.update(iid, closed_at="2026-10-22 09:00")
        with self.assertRaises(ValidationError):
            desk.update(iid, status="encerrado")

    def test_confirming_personal_data_starts_the_clock_now(self):
        desk = make()
        iid = desk.new("Investigando", detected_at="2026-10-20 08:00")
        self.assertIsNone(dl_of(desk, iid, "anpd"))
        desk.update(iid, pd_status="sim")
        inc = desk.store.incident(iid)
        self.assertEqual((inc["pd_aware_at"], inc["anpd_decision"]), ("2026-10-22T10:00", "pendente"))
        self.assertIsNotNone(dl_of(desk, iid, "anpd"))

    def test_ruling_out_personal_data_resolves_the_decision_and_can_be_reverted(self):
        desk = make()
        iid = desk.new("X", pd_status="sim")
        desk.update(iid, pd_status="nao")
        self.assertEqual(desk.store.incident(iid)["anpd_decision"], "nao")
        desk.update(iid, pd_status="sim")
        self.assertEqual(desk.store.incident(iid)["anpd_decision"], "pendente")

    def test_changing_the_awareness_date_requires_a_reason_and_is_logged(self):
        desk = make()
        iid = pd_incident(desk)
        with self.assertRaises(ValidationError) as ctx:
            desk.update(iid, pd_aware_at="2026-10-21 09:00")
        self.assertIn("motivo", str(ctx.exception))
        with self.assertRaises(ValidationError):
            desk.update(iid, reason="curto", pd_aware_at="2026-10-21 09:00")
        desk.update(iid, reason="A equipe confirmou o acesso aos dados só no dia seguinte.", pd_aware_at="2026-10-21 09:00")
        notes = [t for t in desk.timeline(iid) if t["kind"] == "correcao"]
        self.assertEqual(len(notes), 1)
        self.assertIn("só no dia seguinte", notes[0]["text"])
        self.assertEqual(desk.verify(), [])

    def test_status_side_effects_and_reopening(self):
        desk = make()
        iid = desk.new("X", pd_status="nao")
        desk.update(iid, status="contido")
        self.assertEqual(desk.store.incident(iid)["contained_at"], "2026-10-22T10:00")
        desk.update(iid, status="recuperado")
        self.assertEqual(desk.store.incident(iid)["resolved_at"], "2026-10-22T10:00")
        desk.close(iid, root_cause="Falha de configuração corrigida.")
        with self.assertRaises(ValidationError):
            desk.update(iid, severity="alta")                               # encerrado: precisa reabrir
        desk.update(iid, status="em_investigacao")                          # reabertura
        inc = desk.store.incident(iid)
        self.assertEqual((inc["status"], inc["closed_at"]), ("em_investigacao", ""))

    def test_decision_needs_a_justification(self):
        desk = make()
        iid = pd_incident(desk)
        with self.assertRaises(ValidationError):
            desk.decide(iid, "nao", "ok")
        with self.assertRaises(ValidationError):
            desk.decide(iid, "talvez", "Justificativa suficientemente longa.")
        desk.decide(iid, "sim", "Dados financeiros e impacto significativo para os titulares.")
        self.assertEqual(desk.store.incident(iid)["anpd_decision"], "sim")

    def test_deciding_not_to_communicate_warns_when_the_assessment_disagrees(self):
        desk = make()
        iid = pd_incident(desk)
        desk.decide(iid, "nao", "Entendemos que o impacto é pequeno para os titulares.")
        self.assertTrue(any("provável risco relevante" in w for w in desk.warnings))

    def test_communication_registration(self):
        desk = make()
        iid = pd_incident(desk)
        desk.comm(iid, "anpd", "preliminar", "2026-10-21 10:00", ref="PROT-9")
        inc = desk.store.incident(iid)
        self.assertEqual(inc["anpd_decision"], "sim")                        # enviar implica ter decidido comunicar
        with self.assertRaises(ValidationError):
            desk.comm(iid, "jornal", "preliminar")
        with self.assertRaises(ValidationError):
            desk.comm(iid, "anpd", "preliminar", "2026-12-01 10:00")
        with self.assertRaises(PiiError):
            desk.comm(iid, "titulares", "preliminar", notes=f"enviado ao CPF {VALID_CPF}")
        self.assertEqual(len(desk.store.comms(iid)), 1)

    def test_close_rules(self):
        desk = make()
        iid = pd_incident(desk)
        with self.assertRaises(ValidationError):
            desk.close(iid)                                                  # sem causa raiz
        with self.assertRaises(ValidationError) as ctx:
            desk.close(iid, root_cause="Falha humana.")                      # decisão pendente com dados pessoais
        self.assertIn("pendente", str(ctx.exception))
        desk.decide(iid, "sim", "Dados financeiros e impacto significativo para os titulares.")
        desk.close(iid, root_cause="Falha humana no envio.", lessons="Treinar a equipe.", closed_at="2026-10-22 09:00")
        inc = desk.store.incident(iid)
        self.assertEqual((inc["status"], inc["closed_at"], inc["root_cause"]), ("encerrado", "2026-10-22T09:00", "Falha humana no envio."))
        forced = desk.new("Excepcional", pd_status="sim")
        desk.close(forced, force=True)
        self.assertEqual(desk.metrics()["closed_without_cause"], 1)
        self.assertEqual(desk.verify(), [])

    def test_notes_are_checked_for_personal_data(self):
        desk = make()
        iid = desk.new("X")
        with self.assertRaises(PiiError):
            desk.note(iid, f"titular {VALID_CPF}")
        with self.assertRaises(ValidationError):
            desk.note(iid, "  ")
        with self.assertRaises(ValidationError):
            desk.note("INC-2026-9999", "texto")

    def test_timeline_in_order(self):
        desk = make()
        iid = pd_incident(desk)
        desk.note(iid, "Conteve o acesso.", "contencao")
        desk.comm(iid, "anpd", "preliminar", "2026-10-20 10:00", ref="P1")
        kinds = [t["event"] for t in desk.timeline(iid)]
        self.assertEqual(kinds[0], "created")
        self.assertIn("note", kinds)
        self.assertIn("comm", kinds)
        self.assertEqual(desk.timeline(iid)[-1]["event"], "updated")         # a comunicação atualizou a decisão


class DemoScenarioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.desk = build()

    def status(self, iid, key):
        d = dl_of(self.desk, iid, key)
        return d["status"] if d else None

    def test_demo_clock_and_integrity(self):
        self.assertEqual(self.desk.now(), DEMO_NOW)
        self.assertEqual(self.desk.verify(), [])
        self.assertEqual(len(self.desk.store.incidents()), 8)

    def test_every_deadline_situation_is_represented(self):
        self.assertEqual(self.status("INC-2026-0006", "anpd"), "hoje")                  # ransomware: vence hoje, nada enviado
        self.assertEqual(self.status("INC-2026-0005", "anpd"), "cumprido_atraso")       # enviado depois do prazo
        self.assertEqual(self.status("INC-2026-0003", "anpd"), "cumprido")              # no prazo (com o feriado de 12/10 na contagem)
        self.assertEqual(self.status("INC-2026-0003", "declaracao"), "cumprido")
        self.assertIn("provisório", dl_of(self.desk, "INC-2026-0007", "anpd")["note"])  # decisão pendente
        self.assertEqual(self.status("INC-2026-0007", "triagem"), "vencido")
        self.assertEqual(self.status("INC-2026-0008", "triagem"), "vencido")            # notebook: triagem fora da meta
        self.assertIsNone(self.status("INC-2026-0004", "anpd"))                         # decidiu não comunicar
        self.assertEqual(dl_of(self.desk, "INC-2026-0003", "anpd")["due"], datetime(2026, 10, 14, 23, 59))

    def test_metrics(self):
        m = self.desk.metrics()
        self.assertEqual((m["total"], m["open"], m["required"], m["on_time"], m["late"], m["overdue"]), (8, 6, 4, 1, 1, 0))
        self.assertEqual((m["decision_pending"], m["triage_overdue"], m["closed_without_cause"]), (2, 2, 1))
        self.assertEqual(m["avg_hours_to_contain"], 12.1)                  # (2 h + 29 h + 5,33 h) / 3
        self.assertEqual(m["avg_hours_to_resolve"], 72.9)                  # (54 h + 22 h + 142,83 h) / 3

    def test_all_deadlines_are_sorted_by_urgency(self):
        order = {"vencido": 0, "hoje": 1, "a_vencer": 2, "cumprido_atraso": 3, "cumprido": 4}
        ranks = [order[d["status"]] for d in self.desk.all_deadlines()]
        self.assertEqual(ranks, sorted(ranks))


class ReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.desk = build()

    def test_text_outputs(self):
        text = report.render_deadlines(self.desk)
        for expected in ("RELÓGIO DOS PRAZOS", "[VENCIDO]", "[Vence HOJE]", "(LEI)", "(meta)", "confirme"):
            self.assertIn(expected, text)
        self.assertIn("INC-2026-0006", report.render_list(self.desk))
        self.assertNotIn("INC-2026-0002", report.render_list(self.desk))                # encerrado fica fora da lista padrão
        self.assertIn("INC-2026-0002", report.render_list(self.desk, all_incidents=True))
        dossier = report.render_incident(self.desk, "inc-2026-0006")
        for expected in ("AVALIAÇÃO", "DECISÃO", "PRAZOS", "COMUNICAÇÕES", "LINHA DO TEMPO", "Guarda do registro"):
            self.assertIn(expected, dossier)
        self.assertIn("Integridade do registro: OK", report.render_metrics(self.desk))

    def test_html_escapes_titles(self):
        desk = make()
        desk.new("<script>alert(1)</script>", description="<img src=x onerror=alert(1)>")
        doc = report.render_html(desk)
        self.assertNotIn("<script>alert", doc)
        self.assertIn("&lt;script&gt;", doc)

    def test_csv_guard_never_touches_empty_values(self):
        """Regressão do bug do apóstrofo: '' in '=+-@' é True em Python, então um teste por 'in' prefixava células vazias."""
        self.assertEqual(report._safe(""), "")
        self.assertIsNone(report._safe(None))
        for dangerous in ("=1+1", "+1", "-1", "@SUM(A1)", "\tcmd", "\rcmd"):
            self.assertEqual(report._safe(dangerous), "'" + dangerous)

    def test_register_csv_has_every_incident_and_retention(self):
        rows = list(csv.reader(io.StringIO(report.register_csv(self.desk)), delimiter=";"))
        self.assertEqual(len(rows) - 1, 8)                                               # inclui os encerrados e os que não foram comunicados
        header = rows[0]
        by_id = {r[0]: dict(zip(header, r)) for r in rows[1:]}
        self.assertEqual(by_id["INC-2026-0002"]["guardar_ate"], "2031-10-06")
        self.assertEqual(by_id["INC-2026-0004"]["decisao_anpd"], "nao")
        self.assertTrue(by_id["INC-2026-0004"]["justificativa_da_decisao"])
        self.assertTrue(all(c != "'" for r in rows for c in r))

    def test_csv_neutralizes_formulas(self):
        desk = make()
        desk.new("=HYPERLINK(\"http://x\")")
        rows = list(csv.reader(io.StringIO(report.register_csv(desk)), delimiter=";"))
        self.assertEqual(rows[1][1], "'=HYPERLINK(\"http://x\")")

    def test_compliancemap_evidence(self):
        data = json.loads(report.to_compliancemap(self.desk))
        status = {r["control"]: r["status"] for r in data["results"]}
        self.assertEqual(status, {"MON-03": "fail", "MON-04": "fail"})                  # encerrado sem causa raiz; comunicação atrasada e decisões pendentes
        for row in data["results"]:
            self.assertEqual(set(row), {"check", "control", "status", "detail", "platform"})
        empty = json.loads(report.to_compliancemap(make()))
        self.assertEqual({r["status"] for r in empty["results"]}, {"unknown"})
        good = make()
        iid = pd_incident(good)
        good.decide(iid, "sim", "Dados financeiros e impacto significativo para os titulares.")
        good.comm(iid, "anpd", "preliminar", "2026-10-21 10:00")
        good.comm(iid, "titulares", "preliminar", "2026-10-21 11:00")
        good.comm(iid, "anpd", "declaracao_titulares", "2026-10-21 12:00")
        good.note(iid, "Contido.", "contencao")
        good.close(iid, root_cause="Credencial exposta em repositório público.")
        ok = {r["control"]: r["status"] for r in json.loads(report.to_compliancemap(good))["results"]}
        self.assertEqual(ok, {"MON-03": "pass", "MON-04": "pass"})

    def test_compliancemap_flags_a_broken_audit_trail(self):
        path = os.path.join(tempfile.mkdtemp(), "t.db")
        desk = Desk(Store(path), now=NOW)
        desk.new("X", pd_status="nao")
        desk.store.conn.execute("UPDATE incidents SET severity='baixa'")
        desk.store.conn.commit()
        status = {r["control"]: r for r in json.loads(report.to_compliancemap(desk))["results"]}
        self.assertEqual(status["MON-03"]["status"], "fail")
        self.assertIn("integridade", status["MON-03"]["detail"])

    def test_exports_to_other_tools_carry_no_titles_or_descriptions(self):
        blob = report.to_compliancemap(self.desk) + json.dumps(report.to_feed(self.desk), ensure_ascii=False)
        for secret in ("Ransomware no servidor", "Notebook corporativo", "ex-funcionário", "Arquivos criptografados", "Marketing Digital Exemplo"):
            self.assertNotIn(secret, blob)

    def test_feed_has_only_open_incidents(self):
        events = report.to_feed(self.desk)
        self.assertEqual(len(events), 6)
        self.assertTrue(all((e["source"], e["type"], e["ip"]) == ("incidentdesk", "generic", "") for e in events))
        by = {e["message"].split()[1]: e["severity"] for e in events}
        self.assertEqual(by["INC-2026-0006"], "critical")
        self.assertNotIn("INC-2026-0002", by)


class CLITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "t.db")

    def run_cli(self, *argv, stdin=None):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            if stdin is not None:
                with mock.patch("builtins.input", side_effect=stdin):
                    code = main(list(argv))
            else:
                code = main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def cli(self, *argv, **kw):
        return self.run_cli(*argv, "--db", self.db, "--now", "2026-10-22 10:00", **kw)

    def test_full_workflow(self):
        self.assertEqual(self.cli("init")[0], 0)
        code, out, _ = self.cli("new", "--title", "Phishing de credenciais", "--category", "phishing", "--severity", "alta", "--detected", "2026-10-19 08:30",
                                "--pd", "sim", "--aware-at", "2026-10-19 09:00", "--data", "autenticacao", "--titulares", "40", "--significant", "sim")
        self.assertEqual(code, 0)
        self.assertIn("INC-2026-0001", out)
        self.assertIn("22/10/2026 23:59", out)
        self.assertIn("vence HOJE", self.cli("deadlines")[1])
        code, out, _ = self.cli("assess", "INC-2026-0001")
        self.assertIn("Provável risco ou dano relevante", out)
        self.assertEqual(self.cli("note", "INC-2026-0001", "Senhas redefinidas.", "--kind", "contencao")[0], 0)
        self.assertEqual(self.cli("decide", "INC-2026-0001", "--anpd", "sim", "--why", "Credenciais e impacto significativo: critérios atendidos.")[0], 0)
        code, out, _ = self.cli("comm", "INC-2026-0001", "--to", "anpd", "--at", "2026-10-21 17:00", "--ref", "PROT-1")
        self.assertIn("dentro do prazo", out)
        self.assertEqual(self.cli("update", "INC-2026-0001", "--status", "contido")[0], 0)
        self.assertIn("Senhas redefinidas.", self.cli("draft", "INC-2026-0001")[1])
        self.assertIn("senhas", self.cli("draft", "INC-2026-0001", "--kind", "titulares")[1])
        self.assertIn("INC-2026-0001", self.cli("list")[1])
        self.assertIn("LINHA DO TEMPO", self.cli("show", "INC-2026-0001")[1])
        self.assertIn("Integridade do registro: OK", self.cli("metrics")[1])
        self.assertEqual(self.cli("close", "INC-2026-0001")[0], 2)                              # sem causa raiz
        self.assertEqual(self.cli("close", "INC-2026-0001", "--root-cause", "Phishing sem MFA.", "--lessons", "Exigir MFA.")[0], 0)
        self.assertNotIn("INC-2026-0001", self.cli("list")[1])
        self.assertIn("INC-2026-0001", self.cli("list", "--all")[1])
        code, out, _ = self.cli("verify")
        self.assertEqual(code, 0)
        self.assertIn("íntegro", out)

    def test_init_does_not_recreate_and_missing_db_is_an_error(self):
        self.assertEqual(self.cli("init")[0], 0)
        code, _, err = self.cli("init")
        self.assertEqual(code, 2)
        self.assertIn("já existe", err)
        code, _, err = self.run_cli("list", "--db", os.path.join(self.tmp, "nao-existe.db"))
        self.assertEqual(code, 2)
        self.assertIn("init", err)

    def test_personal_data_is_rejected_by_the_cli(self):
        self.cli("init")
        code, _, err = self.cli("new", "--title", f"Vazamento do CPF {VALID_CPF}")
        self.assertEqual(code, 2)
        self.assertIn("CPF", err)
        self.assertIn("Nenhum incidente", self.cli("list", "--all")[1])
        code, _, err = self.cli("new", "--title", "Contato", "--description", "ligar para fulano@exemplo.com.br")
        self.assertEqual(code, 0)
        self.assertIn("Aviso", err)

    def test_verify_fails_after_tampering(self):
        self.cli("init")
        self.cli("new", "--title", "X", "--pd", "sim", "--aware-at", "2026-10-19 09:00", "--detected", "2026-10-19 08:30")
        con = sqlite3.connect(self.db)
        con.execute("UPDATE incidents SET pd_aware_at='2026-10-21T09:00'")
        con.commit()
        con.close()
        code, out, _ = self.cli("verify")
        self.assertEqual(code, 1)
        self.assertIn("ATENÇÃO", out)

    def test_fail_on_overdue_exit_code(self):
        self.cli("init")
        self.cli("new", "--title", "X", "--pd", "sim", "--aware-at", "2026-10-19 09:00", "--detected", "2026-10-19 08:30")
        self.assertEqual(self.cli("deadlines", "--fail-on-overdue")[0], 0)                       # vence hoje, ainda não venceu
        self.assertEqual(self.run_cli("deadlines", "--db", self.db, "--now", "2026-10-23 09:00", "--fail-on-overdue")[0], 1)

    def test_holidays_file_and_now_option_change_the_deadline(self):
        self.cli("init")
        holidays = os.path.join(self.tmp, "h.txt")
        with open(holidays, "w", encoding="utf-8") as f:
            f.write("2026-10-20 Feriado municipal\n")
        _, out, _ = self.cli("new", "--title", "X", "--pd", "sim", "--aware-at", "2026-10-19 09:00", "--detected", "2026-10-19 08:30", "--holidays", holidays)
        self.assertIn("23/10/2026 23:59", out)                                                    # 20/10 não conta

    def test_interactive_new(self):
        self.cli("init")
        answers = ["Notebook perdido", "Criptografado", "perda_dispositivo", "baixa", "", "nao", "controlador", "Suporte"]
        code, out, _ = self.cli("new", "-i", stdin=answers)
        self.assertEqual(code, 0)
        self.assertIn("INC-2026-0001", out)
        self.assertIn("Notebook perdido", self.cli("show", "INC-2026-0001")[1])

    def test_new_without_title_and_unknown_incident(self):
        self.cli("init")
        self.assertEqual(self.cli("new")[0], 2)
        self.assertEqual(self.cli("show", "INC-2026-0099")[0], 2)

    def test_exports(self):
        self.cli("init")
        self.cli("new", "--title", "X", "--severity", "alta")
        paths = {k: os.path.join(self.tmp, "o." + k) for k in ("csv", "html", "cm", "feed")}
        self.assertEqual(self.cli("export", "--csv", paths["csv"])[0], 0)
        self.assertEqual(self.cli("report", "--html", paths["html"])[0], 0)
        self.assertEqual(self.cli("compliancemap", paths["cm"])[0], 0)
        self.assertEqual(self.cli("feed", paths["feed"])[0], 0)
        for p in paths.values():
            self.assertGreater(os.path.getsize(p), 30, p)
        with open(paths["csv"], "rb") as f:
            self.assertEqual(f.read(3), b"\xef\xbb\xbf")                                          # BOM para o Excel

    def test_demo_and_workdays(self):
        code, out, _ = self.run_cli("demo", "--no-color", "--html", os.path.join(self.tmp, "d.html"))
        self.assertEqual(code, 0)
        self.assertIn("FICTÍCIOS", out)
        self.assertIn("MÉTRICAS", out)
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "d.html")))
        code, out, _ = self.run_cli("workdays", "--from", "2026-10-19", "--n", "3")
        self.assertIn("22/10/2026", out)
        self.assertEqual(self.run_cli("workdays", "--from", "ontem")[0], 2)


if __name__ == "__main__":
    unittest.main()
