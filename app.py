#!/usr/bin/env python3
"""IncidentDesk - registro de incidentes de segurança e relógio dos prazos (LGPD / ANPD).
Exemplos:
    python app.py demo                                       # incidentes FICTÍCIOS, relógio simulado
    python app.py init                                       # cria o seu registro (incidentes.db)
    python app.py new --title "..." --category phishing --severity alta
    python app.py deadlines                                  # o que vence e quando
    python app.py workdays --from 2026-10-19 --n 3           # confere uma contagem de dias úteis
"""
import sys

from incidentdesk.cli import main

if __name__ == "__main__":
    sys.exit(main())
