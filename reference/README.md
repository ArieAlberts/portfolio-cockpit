# Portfolio Cockpit v2 — beslissingsondersteunend monitoringsysteem

Dit is een systeem voor beslissingsondersteuning, geen auto-trader. Het plaatst nergens orders.

## Vijf gescheiden modules

1. **QUALITY.** Bij opname geldt `quality_score = 50`, de baseline. Een score boven 50 betekent dat de onderneming fundamenteel verbeterd is, een score onder 50 dat ze verslechterd is. De formule is `clamp(50 + 50·Σ(w·signal), 0, 100)`. De module krijgt geen koers binnen, dus een koersbeweging kan de score niet veranderen.
2. **VALUATION.** Score van 0 tot 100, waarbij 50 ongeveer fair is. Elk bedrijfstype gebruikt alleen multiples die voor dat type zinvol zijn. Een multiple die niet bruikbaar is krijgt `NOT_APPLICABLE`. Een negatieve K/W of negatieve EV/EBITDA telt nooit als goedkoop.
3. **DATA CONFIDENCE.** Score van 0 tot 100, gebaseerd op provenance per datapunt. Onder de 80 wordt de status `DATA_CHECK`. Mogelijke warnings: STALE_DATA, SOURCE_CONFLICT, UNSUITABLE_METRIC, MISSING_DATA en CALCULATION_ANOMALY.
4. **PORTFOLIO RISK.** De kolom heet nu `PORTFOLIO IMPACT -30%` en wordt berekend als gewicht × −30%. Daarnaast zijn er vier configureerbare scenario's.
5. **DECISION ENGINE.** Mogelijke uitkomsten: ADD_CANDIDATE, HOLD, NO_ADD, REVIEW_REDUCE, THESIS_REVIEW en DATA_CHECK. De engine past positie-, sector- en impactlimieten toe.

Daarnaast zijn er nog drie onderdelen:

- **Audit trail.** Alle historie is append-only en wordt beschermd door database-triggers.
- **Simulator.** Draait alleen als dry-run. Ieder signaal wordt gelogd, zodat je later kunt nagaan of het voorspellende waarde had.
- **Dashboard.** Toont Quality en Valuation als twee aparte blokken en heeft een drilldown per aandeel.

Alle drempels en gewichten staan in `config/*.yaml`.

## Gebruik

```bash
pip install pyyaml pytest
pytest -q                 # 43 tests
python run_demo.py        # out/dashboard.html (fictieve data)
```

Postgres: `psql -f migrations/postgres/001_decision_support.sql`

Zie `docs/INTEGRATIE.md` voor de aansluiting op de bestaande codebase.
