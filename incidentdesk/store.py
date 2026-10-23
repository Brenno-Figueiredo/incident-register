"""Armazenamento em SQLite com TRILHA DE AUDITORIA ENCADEADA POR HASH.

Cada acontecimento (criação, alteração, nota, comunicação, decisão) vira um evento. O hash de cada evento inclui o hash do anterior
(como uma blockchain simples): alterar ou apagar um evento antigo quebra a cadeia e o comando 'verify' acusa. O estado atual de
cada incidente também tem um hash gravado no último evento, o que denuncia edições feitas direto na tabela.
Não existe operação de apagar: o registro de incidentes deve ser guardado por no mínimo 5 anos."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime
from typing import Callable, Dict, List, Optional

GENESIS = "0" * 64
STATE_FIELDS = ["title", "description", "category", "severity", "status", "detected_at", "occurred_at", "pd_status", "pd_aware_at", "data_flags",
                "affected_count", "significant_impact", "role", "small_agent", "anpd_decision", "anpd_justification", "bcb_relevant", "systems",
                "vendor", "owner", "root_cause", "lessons", "contained_at", "resolved_at", "closed_at"]
TEXT_DEFAULT = {f: "" for f in STATE_FIELDS}
SCHEMA = f"""
CREATE TABLE IF NOT EXISTS incidents(id TEXT PRIMARY KEY, created_at TEXT, {', '.join(f + ' TEXT' for f in STATE_FIELDS)}, state_hash TEXT);
CREATE TABLE IF NOT EXISTS comms(id INTEGER PRIMARY KEY AUTOINCREMENT, incident_id TEXT, dest TEXT, kind TEXT, sent_at TEXT, ref TEXT, notes TEXT);
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT, incident_id TEXT, ts TEXT, actor TEXT, kind TEXT, payload TEXT, prev_hash TEXT, hash TEXT);
"""


def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def state_hash(fields: Dict[str, str]) -> str:
    return hashlib.sha256(canonical({f: str(fields.get(f, "")) for f in STATE_FIELDS}).encode("utf-8")).hexdigest()


def event_hash(prev: str, ts: str, actor: str, kind: str, incident_id: str, payload: str) -> str:
    return hashlib.sha256("|".join((prev, ts, actor, kind, incident_id, payload)).encode("utf-8")).hexdigest()


class Store:
    def __init__(self, path: str = ":memory:"):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # ---- leitura -----------------------------------------------------------------------------------------------------------------
    def incident(self, iid: str) -> Optional[Dict]:
        row = self.conn.execute("SELECT * FROM incidents WHERE id=?", (iid,)).fetchone()
        return dict(row) if row else None

    def incidents(self) -> List[Dict]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM incidents ORDER BY id")]

    def comms(self, iid: str) -> List[Dict]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM comms WHERE incident_id=? ORDER BY sent_at, id", (iid,))]

    def events(self, iid: Optional[str] = None) -> List[Dict]:
        q, args = ("SELECT * FROM events WHERE incident_id=? ORDER BY id", (iid,)) if iid else ("SELECT * FROM events ORDER BY id", ())
        return [dict(r) for r in self.conn.execute(q, args)]

    def next_id(self, year: int) -> str:
        n = self.conn.execute("SELECT COUNT(*) FROM incidents WHERE id LIKE ?", (f"INC-{year}-%",)).fetchone()[0] + 1
        return f"INC-{year}-{n:04d}"

    # ---- escrita (sempre com evento) ---------------------------------------------------------------------------------------------
    def _append(self, iid: str, kind: str, payload: Dict, ts: datetime, actor: str) -> str:
        last = self.conn.execute("SELECT hash FROM events ORDER BY id DESC LIMIT 1").fetchone()
        prev = last["hash"] if last else GENESIS
        body, stamp = canonical(payload), ts.strftime("%Y-%m-%dT%H:%M:%S")
        h = event_hash(prev, stamp, actor, kind, iid, body)
        self.conn.execute("INSERT INTO events(incident_id, ts, actor, kind, payload, prev_hash, hash) VALUES (?,?,?,?,?,?,?)", (iid, stamp, actor, kind, body, prev, h))
        return h

    def create(self, fields: Dict[str, str], ts: datetime, actor: str) -> str:
        iid = self.next_id(ts.year)
        row = {**TEXT_DEFAULT, **{k: str(v) for k, v in fields.items() if k in STATE_FIELDS}}
        sh = state_hash(row)
        self.conn.execute(f"INSERT INTO incidents(id, created_at, {', '.join(STATE_FIELDS)}, state_hash) VALUES (?,?,{','.join('?' * len(STATE_FIELDS))},?)",
                          (iid, ts.strftime("%Y-%m-%dT%H:%M"), *[row[f] for f in STATE_FIELDS], sh))
        self._append(iid, "created", {"fields": row, "state_hash": sh}, ts, actor)
        self.conn.commit()
        return iid

    def update(self, iid: str, changes: Dict[str, str], ts: datetime, actor: str) -> Dict[str, List[str]]:
        cur = self.incident(iid)
        diff = {k: [cur[k], str(v)] for k, v in changes.items() if k in STATE_FIELDS and cur[k] != str(v)}
        if not diff:
            return {}
        new = {**{f: cur[f] for f in STATE_FIELDS}, **{k: v[1] for k, v in diff.items()}}
        sh = state_hash(new)
        self.conn.execute(f"UPDATE incidents SET {', '.join(k + '=?' for k in diff)}, state_hash=? WHERE id=?", (*[v[1] for v in diff.values()], sh, iid))
        self._append(iid, "updated", {"changes": diff, "state_hash": sh}, ts, actor)
        self.conn.commit()
        return diff

    def note(self, iid: str, kind: str, text: str, ts: datetime, actor: str) -> None:
        self._append(iid, "note", {"kind": kind, "text": text}, ts, actor)
        self.conn.commit()

    def add_comm(self, iid: str, dest: str, kind: str, sent_at: str, ref: str, notes: str, ts: datetime, actor: str) -> int:
        cur = self.conn.execute("INSERT INTO comms(incident_id, dest, kind, sent_at, ref, notes) VALUES (?,?,?,?,?,?)", (iid, dest, kind, sent_at, ref, notes))
        row = {"id": cur.lastrowid, "dest": dest, "kind": kind, "sent_at": sent_at, "ref": ref, "notes": notes}
        self._append(iid, "comm", row, ts, actor)
        self.conn.commit()
        return cur.lastrowid

    def head_hash(self) -> str:
        """Hash do último evento. Guardado fora do computador, serve de ÂNCORA: prova que o histórico até ali não foi reescrito."""
        last = self.conn.execute("SELECT hash FROM events ORDER BY id DESC LIMIT 1").fetchone()
        return last["hash"] if last else GENESIS

    def has_hash(self, h: str) -> bool:
        return bool(self.conn.execute("SELECT 1 FROM events WHERE hash=?", (h.strip().lower(),)).fetchone())

    # ---- verificação da integridade -----------------------------------------------------------------------------------------------
    def verify(self) -> List[str]:
        problems: List[str] = []
        prev = GENESIS
        events = self.events()
        for e in events:
            if e["prev_hash"] != prev:
                problems.append(f"evento {e['id']}: a cadeia foi quebrada (evento removido ou alterado antes deste)")
            expected = event_hash(e["prev_hash"], e["ts"], e["actor"], e["kind"], e["incident_id"], e["payload"])
            if expected != e["hash"]:
                problems.append(f"evento {e['id']} ({e['incident_id']}): o conteúdo foi alterado")
            prev = e["hash"]
        by_incident: Dict[str, Dict] = {}
        comm_events: Dict[int, Dict] = {}
        for e in events:
            payload = json.loads(e["payload"])
            if e["kind"] in ("created", "updated"):
                by_incident[e["incident_id"]] = payload
            if e["kind"] == "comm":
                comm_events[payload["id"]] = payload
        for inc in self.incidents():
            row = {f: inc[f] for f in STATE_FIELDS}
            last = by_incident.get(inc["id"])
            if last is None:
                problems.append(f"{inc['id']}: não há evento de criação para este incidente")
            elif state_hash(row) != last["state_hash"] or inc["state_hash"] != last["state_hash"]:
                problems.append(f"{inc['id']}: os dados do incidente foram alterados fora do programa (hash do estado não confere)")
        rows = {c["id"]: c for iid in [i["id"] for i in self.incidents()] for c in self.comms(iid)}
        for cid, payload in comm_events.items():
            row = rows.get(cid)
            if row is None:
                problems.append(f"comunicação {cid}: removida da tabela")
            elif {k: row[k] for k in ("dest", "kind", "sent_at", "ref", "notes")} != {k: payload[k] for k in ("dest", "kind", "sent_at", "ref", "notes")}:
                problems.append(f"comunicação {cid}: alterada fora do programa")
        for cid in set(rows) - set(comm_events):
            problems.append(f"comunicação {cid}: existe na tabela, mas não na trilha de auditoria")
        return problems
