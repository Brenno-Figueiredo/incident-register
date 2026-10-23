"""Avaliação de risco ou dano relevante (Res. CD/ANPD 15/2024, art. 5º) e rascunhos das comunicações.

A ferramenta SUGERE e prepara textos. A decisão de comunicar, e o envio, são humanos: a comunicação oficial é feita pelos canais da ANPD."""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from .model import DATA_FLAG_LABEL, flags_to_list, from_iso

TODO = "[PREENCHER]"


def assess(inc: Dict) -> Dict:
    """O incidente pode acarretar risco ou dano relevante quando afeta significativamente interesses e direitos fundamentais dos titulares
    E, cumulativamente, envolve ao menos um dos critérios: dados sensíveis; de crianças, adolescentes ou idosos; financeiros; de autenticação;
    protegidos por sigilo; ou em larga escala."""
    criteria = [DATA_FLAG_LABEL[f] for f in flags_to_list(inc["data_flags"]) if f in DATA_FLAG_LABEL]
    sig, pd = inc["significant_impact"], inc["pd_status"]
    if pd == "nao":
        return {"probable": False, "criteria": criteria, "summary": "Nenhum dado pessoal foi afetado: não há comunicação à ANPD. Registre o incidente mesmo assim."}
    if pd == "investigando":
        return {"probable": None, "criteria": criteria, "summary": "Ainda não se sabe se houve dados pessoais afetados. O prazo legal só começa quando isso for confirmado: conclua a triagem."}
    if sig == "avaliando":
        return {"probable": None, "criteria": criteria, "summary": "Avalie se o incidente pode afetar significativamente os interesses e direitos fundamentais dos titulares (primeiro requisito do art. 5º)."}
    if sig == "nao":
        return {"probable": False, "criteria": criteria, "summary": "Impacto significativo descartado: pelo regulamento, em geral não há comunicação obrigatória. Registre a justificativa da decisão."}
    if criteria:
        return {"probable": True, "criteria": criteria, "summary": "Provável risco ou dano relevante: impacto significativo e pelo menos um critério do art. 5º. A comunicação à ANPD e aos titulares provavelmente é obrigatória."}
    return {"probable": False, "criteria": criteria, "summary": "Há impacto significativo, mas nenhum dos critérios do art. 5º foi marcado (os dois requisitos são cumulativos). Revise os tipos de dados antes de concluir."}


def draft_anpd(inc: Dict, notes: List[Dict], late: bool, now: Optional[datetime] = None) -> str:
    containment = [n["text"] for n in notes if n.get("kind") in ("contencao", "mitigacao")]
    flags = [DATA_FLAG_LABEL[f] for f in flags_to_list(inc["data_flags"]) if f in DATA_FLAG_LABEL]
    sensitive = "sim" if "sensiveis" in flags_to_list(inc["data_flags"]) else "não"
    lines = [f"RASCUNHO DE COMUNICAÇÃO DE INCIDENTE DE SEGURANÇA À ANPD ({inc['id']})", "",
             f"Incidente: {inc['title']}", f"Categoria: {inc['category']}   ·   gravidade: {inc['severity']}",
             f"Data/hora em que o controlador soube que o incidente afetou dados pessoais: {from_iso(inc['pd_aware_at']):%d/%m/%Y %H:%M}" if inc["pd_aware_at"] else f"Data/hora em que o controlador soube que o incidente afetou dados pessoais: {TODO}",
             f"Controlador: {TODO}", f"Encarregado (DPO) e contato: {TODO}",
             f"Operador envolvido (se houver): {inc['vendor'] or 'não se aplica'}", "",
             "Conteúdo mínimo (art. 48, § 1º, da LGPD):", "",
             "I - Natureza dos dados pessoais afetados",
             f"   Categorias: {'; '.join(flags) if flags else TODO}   ·   há dados sensíveis? {sensitive}", "",
             "II - Informações sobre os titulares envolvidos", f"   Número estimado de titulares: {inc['affected_count'] or TODO}   ·   perfil dos titulares: {TODO}", "",
             "III - Medidas técnicas e de segurança utilizadas para proteger os dados", f"   {TODO}", "",
             "IV - Riscos relacionados ao incidente e possíveis impactos aos titulares", f"   {TODO}", "",
             "V - Motivos da demora (se a comunicação não foi imediata)",
             "   " + ("A comunicação está FORA do prazo de 3 dias úteis: explique aqui os motivos. " + TODO if late else "Não se aplica: comunicação dentro do prazo."), "",
             "VI - Medidas adotadas ou a adotar para reverter ou mitigar os efeitos"]
    lines += [f"   - {c}" for c in containment] or [f"   {TODO}"]
    lines += ["", "Observações:", "   - Se faltarem informações, envie a comunicação preliminar no prazo e complemente em até 20 dias úteis.",
              "   - Não inclua dados pessoais dos titulares neste texto.", "",
              "Este é um rascunho de apoio. A comunicação oficial é feita pelo canal da ANPD, revisada pelo encarregado e pelo jurídico."]
    return "\n".join(lines)


def draft_titulares(inc: Dict, notes: List[Dict]) -> str:
    flags = flags_to_list(inc["data_flags"])
    advice = []
    if "autenticacao" in flags:
        advice.append("Troque as suas senhas, principalmente se usa a mesma em mais de um serviço, e ative a verificação em duas etapas.")
    if "financeiros" in flags:
        advice.append("Acompanhe as movimentações da sua conta e do seu cartão e desconfie de contatos que peçam dados, senhas ou pagamentos.")
    advice.append("Desconfie de mensagens, ligações ou e-mails inesperados que mencionem este incidente. Confirme sempre pelos nossos canais oficiais.")
    what = [DATA_FLAG_LABEL[f] for f in flags if f in DATA_FLAG_LABEL]
    measures = [n["text"] for n in notes if n.get("kind") in ("contencao", "mitigacao")]
    lines = [f"RASCUNHO DE COMUNICAÇÃO AOS TITULARES ({inc['id']})", "", "Assunto: Comunicado sobre um incidente de segurança envolvendo os seus dados", "",
             "O que aconteceu", f"   {TODO} (descreva em linguagem simples, sem termos técnicos)", "",
             "Quais dados foram envolvidos", f"   {'; '.join(what) if what else TODO}", "",
             "Quais podem ser os riscos para você", f"   {TODO}", "", "O que já fizemos"]
    lines += [f"   - {m}" for m in measures] or [f"   {TODO}"]
    lines += ["", "O que você pode fazer"] + [f"   - {a}" for a in advice]
    lines += ["", "Como falar conosco", f"   Nosso encarregado pela proteção de dados: {TODO} (nome e canal de contato)", "",
              "Rascunho de apoio: revise com o encarregado e o jurídico antes de enviar. Não inclua dados pessoais de outros titulares."]
    return "\n".join(lines)
