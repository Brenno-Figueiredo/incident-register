# IncidentDesk

**Registro de incidentes de segurança com o relógio dos prazos da LGPD e da ANPD**, em Python, **sem dependências externas**.
Ela guarda cada incidente com a linha do tempo, calcula os **prazos em dias úteis** (inclusive com os feriados), ajuda a avaliar se
a comunicação é obrigatória, prepara os rascunhos e mantém uma **trilha de auditoria à prova de adulteração**.

```
python app.py demo                       # incidentes FICTÍCIOS, com o relógio simulado
python app.py init                       # cria o seu registro (incidentes.db)
python app.py deadlines                  # o que vence, e quando
```

## Por que isso importa

Quando um incidente atinge dados pessoais, **começa uma contagem**. A **Res. CD/ANPD 15/2024** (regulamento do art. 48 da LGPD) fixa
o que e quando comunicar, e **registrar o incidente e a decisão tomada** é uma obrigação mesmo quando não se comunica. Em
bancos, a **Res. CMN 4.893** soma o registro e a análise de incidentes e a comunicação tempestiva ao Banco Central.

## O que o regulamento diz (e como a ferramenta usa)

| Regra | Como aparece na ferramenta |
|---|---|
| Comunicar a **ANPD** e os **titulares** em **3 dias úteis**, contados do **conhecimento pelo controlador de que o incidente afetou dados pessoais** | o prazo **só começa** quando você registra que houve dados pessoais (`--pd sim`), e não na detecção |
| **Agentes de pequeno porte**: prazo em dobro | `--small` |
| **Informações complementares**: 20 dias úteis | prazo calculado a partir da comunicação preliminar |
| Só se comunica o incidente que **pode acarretar risco ou dano relevante**: afeta significativamente direitos dos titulares **e**, cumulativamente, envolve ao menos um destes: dados sensíveis; de crianças, adolescentes ou idosos; financeiros; de autenticação; protegidos por sigilo; ou em larga escala | o comando `assess` sugere, com base nos tipos de dados marcados |
| Ressalva: **legislação específica** pode fixar outro prazo (ex.: normas do Banco Central) | prazo **interno** configurável (`--bcb-hours`) |
| O **registro** do incidente, **inclusive o não comunicado**, deve ser mantido por **5 anos** | não existe apagar; o relatório mostra "guardar até" |

> **Fontes e limites.** O texto oficial da Res. CD/ANPD 15/2024 está no site da ANPD e nas bases de legislação. Aqui, os prazos e
> critérios foram **conferidos em resumos de escritórios de advocacia** (fonte secundária), e **uma fonte diverge** sobre o prazo para os
> **titulares** (a maioria diz 3 dias úteis; uma diz "sem demora injustificada"). A ferramenta usa 3 dias úteis e **avisa** no relatório.
> A **declaração à ANPD de que os titulares foram comunicados** também vem de resumo: marcada para confirmação. **Confirme tudo com o
> encarregado (DPO) e o jurídico.** Isto **não é parecer jurídico**.

## Como os dias úteis são contados

- Dia útil = segunda a sexta, **exceto feriados nacionais** (calculados, inclusive a Sexta-feira Santa, e o Dia da Consciência Negra a
  partir de 2024). **Estaduais, municipais e pontos facultativos** você informa: `--holidays arquivo.txt` (exemplo em `samples/`) e
  `--pontos-facultativos` para Carnaval e Corpus Christi.
- **O dia do conhecimento não conta**; o 1º dia útil é o seguinte, e o prazo vai até **23:59** do último dia.
- Para conferir: `python app.py workdays --from 2026-10-19 --n 3` → `22/10/2026`.

## Tipos de prazo
Prazos **legais** (marcados "LEI"): comunicação preliminar à ANPD, comunicação aos titulares, declaração aos titulares e complemento.
Metas **internas** (marcadas "meta"): triagem em 24 h (`--triage-hours`), notificação do controlador quando você é operador, e comunicação ao
Banco Central. **Prazo interno não é prazo legal**: é o que a sua política define.

## Integridade: a trilha de auditoria encadeada por hash

Um registro de incidentes só serve como evidência se não puder ser reescrito sem deixar rastro. Por isso:
- Cada acontecimento (abertura, alteração, nota, comunicação, decisão) é um **evento**, e o hash de cada evento inclui o **hash do anterior**
  (como uma blockchain simples). Alterar ou apagar um evento antigo **quebra a cadeia**. O estado atual de cada incidente também tem um hash, o que
  denuncia **edição direta no arquivo**. `python app.py verify` confere tudo.
- **Não existe comando para apagar.**
- A **data de detecção não pode ser alterada**; mudar a **data de conhecimento** (que muda o prazo legal) **exige um motivo**, que fica registrado.
- A **decisão de comunicar (ou não) exige justificativa**: é ela que prova que o risco foi avaliado.
- **Âncora:** a cadeia sozinha não pega um falsificador que **recalcule tudo**. Por isso o `verify` mostra o **hash final**: anote e guarde **fora
  deste computador**. Depois, `verify --anchor HASH` prova que o histórico até aquele ponto não foi reescrito.

## Privacidade: o registro não guarda dados pessoais
Registre **categorias e quantidades** ("dados financeiros, 12.000 titulares"), **nunca** os dados dos titulares. A ferramenta **bloqueia** textos com
**CPF válido** ou **número de cartão** (confere os dígitos verificadores e o algoritmo de Luhn) e **avisa** sobre e-mails e telefones.
Tudo roda **localmente** (nenhum módulo de rede é usado).

## Fluxo de uso
```bash
python app.py init
python app.py new --title "Phishing de credenciais" --category phishing --severity alta          # prazo ainda não começou
python app.py update INC-2026-0001 --pd sim --data autenticacao --titulares 40 --significant sim  # confirmou dados pessoais: o relógio começa
python app.py assess INC-2026-0001                                                                # há risco relevante?
python app.py decide INC-2026-0001 --anpd sim --why "Credenciais e impacto significativo: critérios do art. 5º atendidos."
python app.py draft INC-2026-0001                                                                 # rascunho (art. 48, § 1º)
python app.py comm INC-2026-0001 --to anpd --ref PROTOCOLO --at "2026-10-21 17:00"                # registra o que você ENVIOU
python app.py close INC-2026-0001 --root-cause "Phishing sem MFA." --lessons "Exigir MFA."
python app.py verify                                                                              # integridade + hash final
```
Outros: `list`, `show`, `note`, `deadlines --fail-on-overdue`, `metrics`, `export --csv`, `report --html`, `new -i` (pergunta um campo por vez).

## Integração com o resto da série
```bash
python app.py compliancemap evidencias-auto.json     # MON-03 e MON-04
python app.py feed feed.jsonl                        # um evento por incidente em aberto
```
- **ComplianceMap:** `assess ... --auto evidencias-auto.json`. **MON-03** (registro e análise) e **MON-04** (comunicação em 3 dias úteis) declarados
  como "implementados" são **rebaixados para "parcial"** quando há incidente encerrado sem causa raiz, comunicação com atraso, decisão pendente
  ou trilha comprometida.
- **Venator / CorrelAI:** eventos **sem título, descrição ou texto livre**.

## Confidencialidade
O registro (`.db`) descreve falhas reais, sistemas, volumes e decisões: **confidencial, com backup, nunca no GitHub** (o `.gitignore` bloqueia). Os
relatórios para outras ferramentas são agregados. Para demonstrações e prints, use **só o `demo`**.

## Estrutura
```
app.py
incidentdesk/
  calendar.py   dias úteis, feriados nacionais (Páscoa calculada), feriados extras
  deadlines.py  o relógio: prazos legais e metas internas
  triage.py     avaliação do art. 5º e rascunhos das comunicações
  store.py      SQLite com trilha de auditoria encadeada por hash e âncora
  desk.py       operações: abrir, atualizar, anotar, comunicar, decidir, encerrar
  model.py      valores permitidos e proteção contra dados pessoais
  report.py     terminal, painel HTML, CSV, métricas, ComplianceMap e feed
  samples.py    8 incidentes FICTÍCIOS (relógio simulado)  ·  cli.py
samples/        arquivo de feriados de exemplo
tests/          72 testes automatizados
```

## Testes
```bash
python -m unittest discover -s tests -v
```
Cobrem o calendário (Páscoa, feriados, contagens), cada prazo, as decisões, a **adulteração da trilha** (evento alterado, apagado, linha editada,
comunicação apagada ou inserida, cadeia recalculada) e os comandos. Os testes mais importantes foram **validados por mutação**: quebrei o código de
propósito (sem os feriados, sem o prazo em dobro, sem o elo da cadeia...) e confirmei que eles falham.

## Limitações (leia)
- **Não é uma ferramenta jurídica**: ela calcula e lembra. A decisão de comunicar e o **envio** são humanos, pelos canais oficiais da ANPD; a ferramenta **não envia nada**.
- Os prazos seguem **resumos secundários** da norma e a **contagem** de dias úteis é a usual: confirme com o jurídico.
- O fuso é o **horário de Brasília**, sem conversão.
- A trilha é **resistente à adulteração, não à prova de adulteração**: sem a **âncora** guardada fora, quem tem acesso ao arquivo e sabe o que faz pode recalcular tudo.
- Um registro em arquivo local atende **uma pessoa ou equipe pequena**. Para uma organização inteira, vale um sistema com controle de acesso por perfil.

## Ideias para evoluir
Painel web com login, lembretes por e-mail antes do vencimento, modelos de comunicação por tipo de incidente, ligação com o `access-review-analyzer` e o
`vendor-risk-assessor` (incidente em terceiro), e exportação do registro em um formato de auditoria assinado.

## Projetos da série
[network-scanner](https://github.com/Brenno-Figueiredo/network-scanner) ·
[logwatch](https://github.com/Brenno-Figueiredo/logwatch) ·
[loginguard](https://github.com/Brenno-Figueiredo/loginguard) ·
[web-vuln-scanner](https://github.com/Brenno-Figueiredo/web-vuln-scanner) ·
[ssh-honeypot](https://github.com/Brenno-Figueiredo/ssh-honeypot) ·
[security-event-correlator](https://github.com/Brenno-Figueiredo/security-event-correlator) ·
[malware-static-analyzer](https://github.com/Brenno-Figueiredo/malware-static-analyzer) ·
[phishguard](https://github.com/Brenno-Figueiredo/phishguard) ·
[phishguard-ui](https://github.com/Brenno-Figueiredo/phishguard-ui) ·
[threat-intel-enricher](https://github.com/Brenno-Figueiredo/threat-intel-enricher) ·
[document-verifier](https://github.com/Brenno-Figueiredo/document-verifier) ·
[compliance-mapper](https://github.com/Brenno-Figueiredo/compliance-mapper) ·
[hardening-auditor](https://github.com/Brenno-Figueiredo/hardening-auditor) ·
[access-review-analyzer](https://github.com/Brenno-Figueiredo/access-review-analyzer) ·
[vendor-risk-assessor](https://github.com/Brenno-Figueiredo/vendor-risk-assessor)
