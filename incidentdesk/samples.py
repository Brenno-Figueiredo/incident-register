"""Incidentes FICTÍCIOS para a demonstração, criados com um relógio simulado (agora = 22/10/2026 10:00, quinta-feira).
Cobre os casos que importam: vence hoje, venceu e foi enviado com atraso, no prazo, decisão pendente, triagem fora da meta e feriado no meio da contagem."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from .calendar import Calendar
from .desk import Desk
from .store import Store

DEMO_NOW = datetime(2026, 10, 22, 10, 0)


def build(path: str = ":memory:", cal: Optional[Calendar] = None) -> Desk:
    clock = {"t": datetime(2026, 9, 28, 10, 0)}
    store = Store(path)
    desk = Desk(store, cal, now=lambda: clock["t"], actor="demo")

    def at(text: str) -> None:
        clock["t"] = datetime.strptime(text, "%Y-%m-%d %H:%M")

    # malware em estação: encerrado SEM causa raiz (para a métrica acusar)
    at("2026-09-28 10:00")
    a = desk.new("Malware detectado em estação de trabalho", "Antivírus bloqueou um executável suspeito.", "malware", "baixa", pd_status="nao", systems="Estação do financeiro", owner="Equipe de TI")
    at("2026-09-30 16:00")
    desk.close(a, force=True)

    # indisponibilidade na nuvem: sem dados pessoais, encerrado com causa raiz
    at("2026-10-05 11:00")
    b = desk.new("Indisponibilidade do sistema de propostas por falha no provedor de nuvem", "", "indisponibilidade", "media", pd_status="nao", systems="Sistema de propostas", owner="Equipe de TI")
    at("2026-10-05 13:00")
    desk.update(b, status="contido")
    at("2026-10-06 09:00")
    desk.close(b, root_cause="Falha de região no provedor sem redundância configurada", lessons="Avaliar redundância entre regiões", closed_at="2026-10-06 09:00")

    # acesso indevido: comunicado NO PRAZO (o feriado de 12/10 entra na contagem)
    at("2026-10-08 09:00")
    c = desk.new("Uso de conta de ex-funcionário para acesso ao sistema", "Conta não desativada após o desligamento.", "acesso_indevido", "alta",
                 pd_status="sim", pd_aware_at="2026-10-08 11:00", data_flags="autenticacao", affected_count=3, significant_impact="sim", systems="Sistema de cadastro", owner="Segurança")
    desk.decide(c, "sim", "Dados de autenticação envolvidos e impacto significativo: critérios do art. 5º atendidos.")
    at("2026-10-13 15:00")
    desk.comm(c, "anpd", "preliminar", "2026-10-13 15:00", ref="PROTOCOLO-EXEMPLO-002")
    at("2026-10-13 16:00")
    desk.comm(c, "titulares", "preliminar", "2026-10-13 16:00")
    at("2026-10-14 10:00")
    desk.comm(c, "anpd", "declaracao_titulares", "2026-10-14 10:00", notes="Declaração de que os titulares foram comunicados.")

    # fornecedor: dados pessoais, mas sem os critérios do art. 5º: decisão de NÃO comunicar, com justificativa
    at("2026-10-12 09:00")
    d = desk.new("Falha em fornecedor de e-mail marketing expôs lista de contatos comerciais", "", "terceiro", "media", pd_status="sim", pd_aware_at="2026-10-13 10:00",
                 significant_impact="nao", vendor="Marketing Digital Exemplo", owner="Marketing")
    at("2026-10-13 14:00")
    desk.decide(d, "nao", "Apenas nomes e e-mails comerciais, sem os critérios do art. 5º; impacto não significativo (avaliado com o encarregado).")
    desk.update(d, status="contido")

    # e-mail enviado por engano: prazo VENCEU e a comunicação foi enviada COM ATRASO
    at("2026-10-14 15:10")
    e = desk.new("Planilha com dados de saúde enviada por e-mail ao destinatário errado", "", "vazamento", "media", pd_status="sim", pd_aware_at="2026-10-14 16:00",
                 data_flags="sensiveis", affected_count=85, significant_impact="sim", systems="E-mail", owner="Operações")
    desk.decide(e, "sim", "Dados sensíveis e impacto significativo para os titulares.")
    at("2026-10-20 09:30")
    desk.comm(e, "anpd", "preliminar", "2026-10-20 09:30", ref="PROTOCOLO-EXEMPLO-003", notes="Enviada após o prazo.")
    at("2026-10-20 14:00")
    desk.comm(e, "titulares", "preliminar", "2026-10-20 14:00")
    desk.update(e, status="recuperado")

    # ransomware: o prazo VENCE HOJE e nada foi enviado
    at("2026-10-19 08:40")
    f = desk.new("Ransomware no servidor de arquivos", "Arquivos criptografados e pedido de resgate.", "ransomware", "critica", pd_status="investigando", systems="Servidor de arquivos", owner="Equipe de TI")
    at("2026-10-19 09:00")
    desk.update(f, pd_status="sim", pd_aware_at="2026-10-19 09:00", data_flags="financeiros,larga_escala", affected_count=12000, significant_impact="sim")
    desk.decide(f, "sim", "Dados financeiros em larga escala e impacto significativo: critérios do art. 5º atendidos.")
    at("2026-10-19 11:00")
    desk.note(f, "Servidor isolado da rede e credenciais redefinidas.", "contencao")
    at("2026-10-19 14:00")
    desk.update(f, status="contido")

    # phishing: decisão ainda PENDENTE (prazo provisório)
    at("2026-10-21 07:50")
    g = desk.new("Campanha de phishing coletou credenciais de funcionários", "", "phishing", "alta", pd_status="sim", pd_aware_at="2026-10-21 10:00",
                 data_flags="autenticacao", affected_count=40, significant_impact="avaliando", systems="E-mail corporativo", owner="Segurança")

    # perda de notebook: a TRIAGEM passou da meta de 24 h
    at("2026-10-21 08:00")
    h = desk.new("Notebook corporativo extraviado", "Equipamento com disco criptografado.", "perda_dispositivo", "baixa", pd_status="investigando", owner="Suporte")
    at("2026-10-22 10:00")
    return desk
