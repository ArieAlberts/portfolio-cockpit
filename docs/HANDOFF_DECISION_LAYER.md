# Handoff — beslissingslaag voor portfolio-cockpit

Uitgangssituatie: `main` @ `19c3605` (3 oktober 2026). 153 tests slagen, Fundamental Quality-snapshot r9, 0 × DISPLAY_READY.

Doel: de beslissingsondersteunende laag uit de oorspronkelijke opdracht bouwen naast de bestaande Fundamental Quality-engine. Die engine blijft ongemoeid.

```
baselines + observaties ─► QUALITY DRIFT ─┐
marktdata + referenties ─► VALUATION ─────┤
bestaande confidence ────► DATA CONFIDENCE ┼─► DECISION ENGINE ─► dashboard
posities + scenario's ──► PORTFOLIO RISK ─┤        │
Fundamental Quality (r9+) ─ alleen context ┘        └─► dry-run simulator + signal-log
```

Lees eerst `CLAUDE.md` (invarianten en de hash-scope van Fundamental Quality). Lees daarna `docs/INVENTARISATIE_2026-10-03.md` als die is toegevoegd, `docs/OPEN_ITEMS.md`, `docs/ARCHITECTURE.md` en `docs/REPRODUCIBLE_SCORING_PIPELINE.md`.

---

## Vastgestelde beslissingen (niet opnieuw ter discussie)

1. **"Quality" uit de opdracht = Quality Drift** uit de repo. Bij opname is de drift exact 50, en hij meet de verandering ten opzichte van de eigen nulmeting. Fundamental Quality (de peer-score) is een aparte as en verandert niet.
2. **De decision engine draait op Drift.** Fundamental Quality voedt de beslissing alleen als context, en alleen wanneer die score DISPLAY_READY is (zie stap 6). Daardoor werkt de beslissingslaag nu al voor alle 23 posities, ook zonder peer-data.
3. **Geen database.** Uitvoer gaat als immutable JSON-revisies naar `data/<as>/…_rN.json`, met een `current.json`-pointer, volgens hetzelfde patroon als `data/scoring/`.
4. **Nieuw package `src/portfolio_cockpit/decision_layer/`** met eigen configbestanden. Geen wijzigingen aan bestanden die in de Fundamental Quality-hash vallen (zie `CLAUDE.md`). Lezen mag wel, bijvoorbeeld `metric_directions` uit `score_metrics.yaml`.
5. **De repo mag publiek blijven**, dat is een besluit van de eigenaar. Posities en thesis-status mogen daarom in de repo-config staan.
6. **Geen orders.** De simulator is altijd een dry-run.

---

## Stap 1 — Package-skelet en configloader

Nieuw:

- `src/portfolio_cockpit/decision_layer/__init__.py`
- `decision_layer/config.py`: `load_decision_config(root)` en `validate_decision_config(cfg, repo_cfg)` (fail-fast).
- `decision_layer/io.py`: een generieke variant van `write_immutable_snapshot` / `update_current_pointer` met parameters `output_dir`, `prefix` en `pointer_name`. Kopieer de logica; importeer haar niet uit `scoring/pipeline.py`, zodat die module niet verandert. Inclusief het reproducibility-hash-hergebruik en byte-stabiele no-op-rebuilds.
- Nieuwe configbestanden (inhoud in de volgende stappen):
  - `config/quality_drift.yaml`
  - `config/valuation.yaml`
  - `config/decision.yaml`
  - `config/risk_scenarios.yaml`
  - `config/positions.yaml`
  - `config/thesis_status.yaml`

Acceptatie:

- Een test laadt de echte repo-config zonder fouten.
- Een test controleert dat er geen enkel FQ-gehasht bestand is gewijzigd (vergelijk `CONFIG_FILES`/`CODE_FILES` uit `scoring/pipeline.py` met `git diff --name-only origin/main`, of hardcode de lijst in de test).

## Stap 2 — Quality Drift-engine

### Inputs

- **Nulmeting:** `data/baselines/index.json` → `data/baselines/<T>/<datum>.json`. Alleen lezen. De metrics staan genest per component, bijvoorbeeld `metrics.capital_strength.solvency_ii_ratio_pct`. De metricnamen verschillen per bedrijf.
- **Observaties (nieuw):** `data/observations/<T>/<datum>.json`, met dezelfde nesting als de nulmeting. Per metric:
  ```json
  {"value": 182.0, "period": "FY2026", "period_basis": "FY",
   "source": {"source_type": "OFFICIAL_COMPANY_REPORT", "title": "...", "url": "...",
              "publication_date": "2027-02-20", "report_id": "..."},
   "retrieved_at": "2027-02-21T09:00:00Z", "currency": "EUR",
   "calculation_method": "reported"}
  ```
  Plus de velden `ticker`, `observation_date`, `reporting_period_end` en `schema_version: 1`. Een observatie wordt nooit overschreven; een correctie wordt een nieuw bestand.

### Config `config/quality_drift.yaml`

```yaml
schema_version: 1
formula: "clamp(50 + 50 * sum(component_weight * component_signal), 0, 100)"
minimum_component_weight_coverage: 0.70
period_rule: like_for_like       # H1 met H1, FY met FY, TTM met TTM; anders metric uitsluiten
profiles:
  INSURER:
    required_components: [capital_strength, profitability]
    components:
      capital_strength:
        weight: 0.30
        slots:
          solvency:
            weight: 1.0
            aliases: [solvency_ii_ratio_pct, solvency_ratio_pct]
            direction: higher_is_better
            mode: absolute          # relative | absolute | direct
            full_scale: 30.0        # verandering die ±1 oplevert
            dead_band: 3.0
      # ... profitability, capital_generation, value_per_share, capital_allocation
  # GENERAL_OPERATING_COMPANY, INSURER_US_P&C, FINANCIAL_SERVICES,
  # CYCLICAL_MINING, PRE_REVENUE_DEVELOPMENT
```

Stel de profielen en aliases op **uit de echte metricnamen in alle 23 nulmetingen**. Schrijf eerst een script dat per `company_type` alle `component.metric`-paden uit `data/baselines/**` oplijst, en stel het profiel daarop samen.

De componentnamen in de nulmetingen wijken soms af van `company_types.yaml`. Zo heeft ASR `capital_generation` en `capital_allocation`. `config/confidence.yaml: baseline_component_aliases` bevat al een eerste mapping.

Absolute bedragen (`*_eur_m`, `*_usd_m`) gebruiken `mode: relative`. Percentages en ratio's gebruiken `mode: absolute`. Beoordelingen (−1..+1) gebruiken `mode: direct`.

`*_prior_*`-velden in de nulmeting zijn **geen** drift-input; die beschrijven de periode vóór de nulmeting.

Richting: neem de richting uit `score_metrics.yaml: metric_directions[company_type]` als de metric daar staat. De validator faalt als de drift-config een tegenstrijdige richting opgeeft.

### Berekening

- Per slot geldt:
  ```
  delta = (raw − baseline) / |baseline|  (relative)  of  raw − baseline  (absolute/direct)
  normalized_signal = clamp(delta_effectief / full_scale, −1, 1)
  ```
  Binnen de dead band telt de verandering als 0. Bij `lower_is_better` wordt het teken omgedraaid.
- Het component-signaal is het gewogen gemiddelde over de beschikbare slots. De slotgewichten worden herverdeeld (zelfde regel als bij Fundamental Quality), zolang de dekking binnen het component ≥ 0,50 is.
- `drift = clamp(50 + 50 · Σ w_c · s_c / Σ w_c(beschikbaar), 0, 100)`.
- Zonder observaties na de nulmeting is de drift **exact 50.0**, met status `NO_NEW_FUNDAMENTALS`.
- Ontbreekt een verplicht component, of is de dekking lager dan 0,70, dan wordt de status `DRIFT_DATA_CHECK`. De score wordt dan alleen diagnostisch bewaard.
- Een verschil in periodebasis (H1 tegenover FY) sluit de metric uit, met de warning `PERIOD_MISMATCH:<metric>`.

### Uitvoer

`data/drift/quality_drift_<as_of>[_rN].json` en `data/drift/current.json`.

Per ticker:

- `drift_score`, `drift_change_since_baseline` (= score − 50), `drift_change_recent` (verschil met de vorige revisie);
- `status`, `coverage`;
- per metric: `baseline_value`, `baseline_date`, `baseline_source`, `previous_value`, `raw_value`, `delta`, `normalized_signal`, `contribution_points` (= 50 · w · s) en de bron met datum.

Daarnaast de provenance-hashes van config, code, nulmeting en observatie.

CLI: `cockpit-drift [--write]` (entry point in `pyproject.toml`).

### Tests

- Nulmeting = 50.0 voor alle 23 tickers.
- Een observatie met dezelfde waarden als de nulmeting geeft 50.0.
- Monotonie per richting (Hypothesis).
- Clamp naar 0 en 100.
- Dead band.
- Period mismatch sluit de metric uit.
- Een ontbrekend verplicht component geeft `DRIFT_DATA_CHECK`.
- De nulmeting kan niet veranderen: SHA-256 van elk bestand in `data/baselines/index.json`, vastgelegd in een fixturebestand `tests/fixtures/baseline_hashes.json`. Een wijziging laat de test falen.
- Drift-code importeert niets uit marktdata of valuation (AST-test).
- No-op rebuild is byte-stabiel.

## Stap 3 — Valuation-engine

### Inputs

- **Marktdata (nieuw):** `data/market/<datum>.json`, handmatig of via een latere adapter. Per ticker: `price`, `shares_outstanding`, `net_debt`, `currency` en de benodigde fundamentals (`forward_eps`, `eps_ttm`, `ebit`, `ebitda`, `fcf`, `bvps`, `distributions_ttm`, `navps`, `risked_npv`). Elk veld heeft provenance; de koersdatum heeft een maximale leeftijd van 7 dagen.
- **Referenties (nieuw):** `data/valuation_refs/<T>.json` met `own_history` (bijvoorbeeld de mediaan over 5 jaar) en `peers` (mediaan), per multiple, met bron en methode.

### Config `config/valuation.yaml`

Profielen per `company_type`, met gewichten en een lijst `not_applicable`:

- **GENERAL_OPERATING_COMPANY:** forward P/E, EV/EBIT, FCF-yield.
- **INSURER en INSURER_US_P&C:** P/B, P/E, shareholder yield. Niet van toepassing: EV/EBITDA, EV/EBIT en FCF-yield.
- **PRE_REVENUE_DEVELOPMENT:** P/NAV en market cap / risked NPV. Niet van toepassing: P/E, forward P/E, EV/EBITDA, EV/EBIT en FCF-yield.
- **CYCLICAL_MINING:** P/NAV, EV / genormaliseerde EBITDA en FCF-yield.
- **FINANCIAL_SERVICES:** zelf voorstellen. Waarschijnlijk P/E en P/B. Leg de keuze voor aan de eigenaar.

De labels (`Attractive` ≥60, `Fair` ≥45, anders `Expensive`) en de referentiegewichten (eigen historie 0,6, peers 0,4) staan in de config.

### Regels

- Een negatieve of nul noemer geeft `NOT_APPLICABLE`. **Een negatieve P/E of EV/EBITDA is nooit goedkoop.**
- Elke metric bevat: `value`, `status`, `score`, `reference_value`, `source`, `as_of_date`, `calculation_method` en `raw_inputs`.
- Formules staan in een whitelist-register (dict van naam naar functie). Geen `eval`.

### Uitvoer en CLI

- Uitvoer: `data/valuation/valuation_<as_of>[_rN].json` met `current.json`.
- CLI: `cockpit-valuation [--write]`.

### Tests

- Een koersverandering alleen verandert de Valuation en niet de Drift. Dit is een end-to-end-test over beide CLI's of functies.
- Bij een verzekeraar zijn EV/EBITDA en FCF `NOT_APPLICABLE`.
- Bij een pre-revenue bedrijf geen P/E-interpretatie.
- Een negatieve P/E of EV/EBITDA geeft `NOT_APPLICABLE`.
- Provenance-velden zijn aanwezig.
- Er wordt nooit gerekend zonder referentie (status `NO_REFERENCE`).

## Stap 4 — Contract voor de Data Confidence-warnings

Maak `decision_layer/warnings.py` met een vaste enum:

- STALE_DATA
- SOURCE_CONFLICT
- UNSUITABLE_METRIC
- MISSING_DATA
- CALCULATION_ANOMALY
- PERIOD_MISMATCH

Map de bestaande confidence-uitkomsten en de nieuwe drift- en valuation-warnings hierop. De decision engine leest de data confidence per ticker uit de bestaande `data/confidence/<datum>.json`. Verander de bestaande confidence-berekening niet.

Regels:

- Een koers ouder dan 7 dagen geeft `STALE_DATA` op de valuation.
- Een fundamentele observatie ouder dan 200 dagen geeft `STALE_DATA` op de drift.

Beide drempels staan in de config.

Tests:

- Ontbrekende data leidt uiteindelijk tot `DATA_CHECK`.
- Verouderde data geeft een warning.

## Stap 5 — Portfolio Risk

### Config

- `config/positions.yaml`: de **huidige** gewichten per ticker, plus `as_of`, `cash_weight` en `source: manual`. Later komt hier een read-only IBKR-adapter voor.
- De doelgewichten blijven uit `config/portfolio.yaml` komen en worden **alleen gelezen**.

### Module `decision_layer/risk.py`

- Het label is `PORTFOLIO IMPACT -30%`: `impact_pp = weight × −0,30 × 100`.
- Sectorgewichten.
- Scenario's uit `config/risk_scenarios.yaml`:
  - `market_shock` (optioneel met beta);
  - `sector_shock`;
  - `single_stock_shock`;
  - `combined_scenario`.
- De bestaande `scoring/portfolio_risk.py` blijft ongewijzigd en mag worden hergebruikt.
- Sector per ticker: voeg `sector` toe in `positions.yaml`, niet in `portfolio.yaml`, want die staat in de FQ-hash.

### Tests

- 7% × −30% = −2,1 procentpunt.
- Elk scenariotype.
- De sectorgewichten tellen op tot de som van de gewichten.

## Stap 6 — Decision Engine

### Inputs per ticker

- `drift_score` en `drift_change_recent`;
- `valuation_score`;
- `data_confidence`;
- `thesis_status` (uit `config/thesis_status.yaml`: INTACT, WATCH of BROKEN, plus `as_of` en een korte toelichting; verplicht voor alle 23 tickers);
- `portfolio_weight`, `base_target_weight`, `sector_weight` en `portfolio_impact_pp`;
- optioneel de Fundamental Quality uit `data/scoring/current.json`.

### Logica

Alle drempels staan in `config/decision.yaml`.

```
if data_confidence < 80                         → DATA_CHECK   (ook als drift of valuation DATA_CHECK zijn)
elif thesis_status == BROKEN                     → THESIS_REVIEW
elif drift ≤ 40 or drift_change_recent ≤ −10     → REVIEW_REDUCE
elif drift ≥ 55 and valuation ≥ 60               → ADD_CANDIDATE, tenzij een limiet geraakt wordt → HOLD + limit_flags
elif drift ≥ 45 and valuation < 45               → NO_ADD
else                                             → HOLD
```

### Limieten

- `max_position_weight`;
- `overweight_tolerance` ten opzichte van het basisgewicht;
- `max_sector_weight`;
- `max_single_position_impact_pp`.

### Fundamental Quality als context

- Fundamental Quality DISPLAY_READY én onder `fq_add_floor` (configureerbaar, bijvoorbeeld 35): ADD_CANDIDATE wordt HOLD, met reden `FQ_BELOW_FLOOR`.
- Fundamental Quality niet DISPLAY_READY: geen invloed, alleen de vermelding `FQ_NOT_DISPLAY_READY` in de redenen.

### Uitvoer

- `data/decisions/decisions_<as_of>[_rN].json` met `current.json`.
- Per ticker: `decision_state`, `reasons`, `limit_flags` en alle inputwaarden met de paden en hashes van de bronbestanden.
- Altijd `execution_effect: NONE`.
- Geen ordervelden.

CLI: `cockpit-decide [--write]`. Die leest de actuele `current.json` van drift, valuation en scoring.

### Tests

- Elke tak van de beslisboom (geparametriseerd).
- DATA_CHECK gaat vóór alles.
- Limieten blokkeren ADD.
- De Fundamental Quality-floor werkt alleen bij DISPLAY_READY.
- De output bevat nooit `side`, `quantity`, `limit_price` of `order_id`.
- Het package importeert geen broker-SDK.
- `base_target_weight` is na een run ongewijzigd (hash van `portfolio.yaml`).
- Historische beslissingen blijven bewaard (revisies worden nooit overschreven).

## Stap 7 — Dashboard

`decision_layer/dashboard.py` en `scripts/build_dashboard.py` maken `out/dashboard.html`: één statisch bestand, geen externe hosts. `out/` komt in `.gitignore`, tenzij de eigenaar het anders wil.

### Kolommen

- Ticker
- Portfolio weight
- Base target weight
- Price
- **Quality Drift**, bijvoorbeeld "62 (+12 since baseline)"
- **Fundamental Quality (peer)**: de score bij DISPLAY_READY, anders "n.v.t. (DATA_CHECK)" met de diagnostische band in een tooltip
- **Valuation**, bijvoorbeeld "43 / Expensive"
- Data confidence
- PORTFOLIO IMPACT -30%
- Thesis status
- Decision state
- Last fundamental update
- Last valuation update
- Warnings

Drift en Valuation krijgen elk een eigen kleur of blok.

### Doorklikken per ticker

- Drift-metrics die omhoog en omlaag gingen: oud tegenover nieuw, bijdrage in punten, bron en datum.
- Valuation-metrics met status, referentie en methode.
- Componenten van de confidence.
- Historie van alle revisies.

### Tests

- Het woord "percentiel"/"percentile" komt niet voor in de gegenereerde HTML.
- Het label `PORTFOLIO IMPACT -30%` komt erin voor.
- Er is geen `<script src=http…>`.

## Stap 8 — Simulator en signal-log

`decision_layer/simulator.py`, met per ticker:

- `current_weight` en `base_target_weight`;
- `suggested_review_direction`: `REVIEW_UP_TO_TARGET` (alleen bij ADD_CANDIDATE en een gewicht onder het doel), `REVIEW_DOWN` (bij REVIEW_REDUCE), `REVIEW_THESIS`, `NONE` of `NONE (DATA_CHECK)`;
- `difference`;
- portfolio impact nu en bij het doelgewicht;
- sectorimpact;
- cash-impact.

`dry_run: true` is hard: de constructor weigert `False`.

### Signal-log

Append-only `data/signal_log/<as_of>.jsonl`, met per signaal de koers, de state en de inputs.

`cockpit-evaluate-signals --horizon 90d` berekent het forward-rendement per decision_state, vergeleken met het gemiddelde van de portefeuille.

### Tests

- De simulator is altijd een dry-run.
- Het basisgewicht verandert nooit.
- Cash-impact en sectorimpact zijn correct.
- De evaluatie van de signalen is correct.

## Stap 9 — CI en documentatie

- `.github/workflows/tests.yml`: smoke-tests voor `cockpit-drift --help`, `cockpit-valuation --help`, `cockpit-decide --help` en `scripts/build_dashboard.py --help`.
- Optioneel een workflow `rebuild-decision-layer.yml`. Die triggert op `data/observations/**`, `data/market/**`, `config/{quality_drift,valuation,decision,risk_scenarios,positions,thesis_status}.yaml` en `src/portfolio_cockpit/decision_layer/**`, en schrijft revisies met `--write` (zelfde patroon als `rebuild-fundamental-quality.yml`).
- Documentatie:
  - `docs/DECISION_LAYER.md`: architectuur, formules en statussen;
  - `docs/OPEN_ITEMS.md` bijwerken;
  - `docs/ARCHITECTURE.md`: "50 = relevant peer median" corrigeren naar "peer mean". Dat bestand valt niet in de hash.

---

## Data die de eigenaar moet aanleveren

Het systeem verzint deze gegevens niet.

| Bestand | Wat | Wanneer |
|---|---|---|
| `config/positions.yaml` | Huidige gewichten, sector en eventueel beta per ticker | Vóór stap 5. Zonder dit bestand weigert de decision engine te draaien, met een duidelijke fout. |
| `config/thesis_status.yaml` | INTACT, WATCH of BROKEN per ticker, met toelichting | Vóór stap 6 |
| `data/market/<datum>.json` | Koers en aantal aandelen, plus valuation-inputs | Vóór stap 3. Begin met 2 à 3 tickers. |
| `data/valuation_refs/<T>.json` | Eigen historische en peer-multiples (bijvoorbeeld uit InvestingPro), met bron | Vóór stap 3 |
| `data/observations/<T>/…` | De eerste fundamentele update na de nulmeting (bijvoorbeeld de Q3-cijfers) | Wanneer beschikbaar. Tot dan staat de drift terecht op 50. |

Laat Claude Code voor elk bestand eerst een **template met lege waarden** genereren, plus een validator die precies zegt wat er ontbreekt.

## Referentiecode

`reference/` bevat een werkend prototype (SQLite-variant, 43 tests) van precies deze modules. Gebruik het als bron voor logica en tests; neem de opslaglaag niet over. Relevante bestanden:

- `reference/cockpit/decision.py`: beslisboom en limieten;
- `reference/cockpit/simulator.py`: dry-run en signaalevaluatie;
- `reference/cockpit/risk.py`: scenario's;
- `reference/cockpit/valuation.py`: formuleregister en de regels voor NOT_APPLICABLE;
- `reference/cockpit/quality.py`: `normalize()` met dead band, full_scale en richting. Dit is de drift-kern.
- `reference/cockpit/confidence.py`: warning-detectie (stale, conflict, anomaly);
- `reference/cockpit/dashboard.py`: HTML-template met drilldown;
- `reference/config/*.yaml` en `reference/tests/test_cockpit.py`.
