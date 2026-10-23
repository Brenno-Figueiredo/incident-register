"""Campos, valores permitidos e proteção contra dados pessoais nos textos.

Regra de privacidade do projeto: o registro guarda CATEGORIAS e QUANTIDADES de dados afetados, NUNCA os dados pessoais dos titulares."""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from typing import Dict, List, Optional, Tuple

CATEGORIES = ("ransomware", "vazamento", "acesso_indevido", "phishing", "malware", "indisponibilidade", "perda_dispositivo", "fraude", "terceiro", "outro")
SEVERITIES = ("baixa", "media", "alta", "critica")
STATUSES = ("aberto", "em_investigacao", "contido", "erradicado", "recuperado", "encerrado")
DATA_FLAGS = ("sensiveis", "criancas_idosos", "financeiros", "autenticacao", "sigilo", "larga_escala")
DATA_FLAG_LABEL = {"sensiveis": "dados pessoais sensíveis", "criancas_idosos": "dados de crianças, adolescentes ou idosos", "financeiros": "dados financeiros",
                   "autenticacao": "dados de autenticação em sistemas", "sigilo": "dados protegidos por sigilo legal, judicial ou profissional",
                   "larga_escala": "dados em larga escala"}
TRI = ("sim", "nao", "avaliando")
PD_STATUS = ("sim", "nao", "investigando")
DECISIONS = ("pendente", "sim", "nao")
ROLES = ("controlador", "operador")
COMM_TO = ("anpd", "titulares", "bcb", "controlador", "cliente", "outro")
COMM_KIND = ("preliminar", "complementar", "declaracao_titulares", "outra")
SEVERITY_TO_FEED = {"baixa": "low", "media": "medium", "alta": "high", "critica": "critical"}


class ValidationError(ValueError):
    """Valor inválido informado pelo usuário."""


class PiiError(ValidationError):
    """O texto parece conter dado pessoal de titular (CPF, número de cartão)."""


def norm(text) -> str:
    s = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", s).strip()


def choice(value, options: Tuple[str, ...], label: str, default: Optional[str] = None) -> str:
    t = norm(value).replace(" ", "_")
    if not t and default is not None:
        return default
    if t not in options:
        raise ValidationError(f"{label} inválido: '{value}'. Use: {', '.join(options)}")
    return t


def parse_dt(value, label: str = "data/hora") -> Optional[datetime]:
    """Aceita 'AAAA-MM-DD HH:MM', 'dd/mm/aaaa HH:MM' ou só a data (assume 00:00). Sem fuso: use o horário de Brasília."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.replace(second=0, microsecond=0)
    text = str(value).strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    raise ValidationError(f"{label} inválida: '{value}'. Use AAAA-MM-DD HH:MM ou dd/mm/aaaa HH:MM")


def iso(dt: Optional[datetime]) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M") if dt else ""


def from_iso(text: str) -> Optional[datetime]:
    return datetime.strptime(text, "%Y-%m-%dT%H:%M") if text else None


def flags_to_list(text: str) -> List[str]:
    return [f for f in (text or "").split(",") if f]


def parse_flags(value) -> str:
    parts = [norm(p).replace(" ", "_") for p in (value.split(",") if isinstance(value, str) else (value or [])) if str(p).strip()]
    bad = [p for p in parts if p not in DATA_FLAGS]
    if bad:
        raise ValidationError(f"tipo de dado inválido: {', '.join(bad)}. Use: {', '.join(DATA_FLAGS)}")
    return ",".join(sorted(set(parts)))


# ---- proteção contra dados pessoais nos textos livres --------------------------------------------------------------------------
_CPF = re.compile(r"(?<!\d)(\d{3}\.?\d{3}\.?\d{3}-?\d{2})(?!\d)")
_CARD = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE = re.compile(r"(?:\+55\s?)?\(\d{2}\)\s?9?\d{4}-?\d{4}")


def _valid_cpf(digits: str) -> bool:
    if len(digits) != 11 or len(set(digits)) == 1:
        return False
    for n in (9, 10):
        total = sum(int(d) * w for d, w in zip(digits[:n], range(n + 1, 1, -1)))
        if str((total * 10) % 11 % 10) != digits[n]:
            return False
    return True


def _luhn(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2:
            n = n * 2 - 9 if n * 2 > 9 else n * 2
        total += n
    return total % 10 == 0


def scan_pii(text: str) -> Dict[str, int]:
    """Conta o que parece dado pessoal. CPF (com dígito verificador correto) e cartão (Luhn) são BLOQUEADOS; e-mail e telefone só geram aviso."""
    found = {"cpf": 0, "cartao": 0, "email": 0, "telefone": 0}
    for m in _CPF.finditer(text or ""):
        if _valid_cpf(re.sub(r"\D", "", m.group(1))):
            found["cpf"] += 1
    for m in _CARD.finditer(text or ""):
        digits = re.sub(r"\D", "", m.group(0))
        if 13 <= len(digits) <= 19 and _luhn(digits) and not _valid_cpf(digits[:11]):
            found["cartao"] += 1
    found["email"] = len(_EMAIL.findall(text or ""))
    found["telefone"] = len(_PHONE.findall(text or ""))
    return found


def check_text(text: str, label: str = "texto") -> List[str]:
    """Levanta PiiError se houver CPF ou cartão; devolve avisos para e-mail e telefone."""
    f = scan_pii(text)
    if f["cpf"] or f["cartao"]:
        what = ", ".join(n for n, c in (("CPF", f["cpf"]), ("número de cartão", f["cartao"])) if c)
        raise PiiError(f"o {label} parece conter {what}. Remova: o registro guarda só categorias e quantidades de dados, nunca os dados dos titulares.")
    warnings = []
    if f["email"]:
        warnings.append(f"o {label} contém {f['email']} endereço(s) de e-mail: confirme que não é dado de titular")
    if f["telefone"]:
        warnings.append(f"o {label} contém {f['telefone']} telefone(s): confirme que não é dado de titular")
    return warnings
