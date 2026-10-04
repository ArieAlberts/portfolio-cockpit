# Inventarisatie portfolio-cockpit — 3 oktober 2026

Basis: `main` @ `46c18c0`.

> **Update (`19c3605`):** de verouderde ASR-test is inmiddels gecorrigeerd. De suite staat op 153 geslaagd, 0 mislukt, en het actuele snapshot is r9. De rest van deze inventarisatie geldt nog steeds. Deze inventarisatie vergelijkt de bestaande code met de herstructureringsopdracht (vijf modules: Quality, Valuation, Data Confidence, Portfolio Risk en Decision Engine, plus dashboard, historie en simulator).

Testsuite: **145 geslaagd, 1 mislukt.** `compileall` is OK. Er staan geen secrets in de code of de git-historie; de enige auteurs zijn noreply-adressen.

## 0. Belangrijkste bevinding: de begrippen passen al op elkaar

De opdracht definieert **QUALITY** als: 50 bij opname, verandering ten opzichte van de nulmeting, niet koersgevoelig. In de repo heet dat al **Quality Drift**:

- `scoring/drift.py`
- `scoring.yaml: quality_drift`
- `CompanyBaseline.quality_drift_score`

De peer-relatieve **Fundamental Quality** (z-score, 50 = peer-gemiddelde) is een aparte, tweede as. Die is al ver uitgewerkt.

Voorstel: we houden de repo-namen aan. In het dashboard worden het:

- **Quality Drift**, bijvoorbeeld "62 (+12 since baseline)";
- **Fundamental Quality (peer)**, bijvoorbeeld "42 / peer-gemiddelde 50";
- **Valuation**, bijvoorbeeld "43 / Expensive".

Drie visueel gescheiden blokken. Nergens het woord "percentiel".

## 1. Stand per module

| Module | Stand in de repo | Gat ten opzichte van de opdracht |
|---|---|---|
| Fundamental Quality (peer) | **Volwassen.** Uitgeschakeld doelbedrijf in de peer-statistiek, sample-std, clip ±3, minimaal 4 peers, slot-gewichten binnen componenten met minimale dekking, leave-one-out STABLE/PEER_SENSITIVE/UNSTABLE, required components, reproducibility-hashes, immutable revisies. | Geen gat. Op dit moment zijn alle 23 bedrijven `DATA_CHECK` vanwege peer-dekking. Dat is terecht streng. |
| **Quality Drift** (= QUALITY uit de opdracht) | **Stub.** Alleen `50 + 50·signal`. Nulmetingen bestaan als JSON per ticker (`data/baselines/<T>/<datum>.json`), met metrics genest per component. | Ontbreekt: periodieke observaties, `delta_vs_baseline`, `normalized_signal` met drempels uit config, profielen per bedrijfstype, opslag in historie, uitleg per metric. |
| Valuation | **Stub.** Alleen een functie van z naar score. | Alles ontbreekt: metrics per type, `NOT_APPLICABLE`, eigen historie + peers, provenance, regel "negatieve K/W is nooit goedkoop". |
| Data Confidence | **Werkend.** Doel- en peer-confidence, drempel 80 → `DATA_CHECK`, cross-checks. | De vijf warning-codes (STALE_DATA, SOURCE_CONFLICT, UNSUITABLE_METRIC, MISSING_DATA, CALCULATION_ANOMALY) zijn nog geen vast contract. Alleen `STALE_DATA` bestaat, en dan in de monitor. |
| Portfolio Risk | **Stub.** `portfolio_impact(weight, shock)`. Er bestaat geen kolom "STRESS -30%" in de code, dus er hoeft niets hernoemd te worden. | Ontbreken: het label `PORTFOLIO IMPACT -30%`, scenario's (markt, sector, enkel aandeel, gecombineerd) en sectorgewichten. |
| Decision Engine | **Ontbreekt.** | Volledig te bouwen. |
| Dashboard | **Ontbreekt.** | Volledig te bouwen. |
| Historie & audit | Voor Fundamental Quality uitstekend (immutable revisies, `current.json`). | Drift, Valuation en Decision hebben nog geen historie. |
| Simulator + signal-log | **Ontbreekt.** Er is wel een `ProposedOrderTicketBuilder` en een harde no-live-grens. | Dry-run-simulator en signal-log zijn te bouwen. |
| Monitoring | Gebouwd, maar nog niet gedraaid: alle 23 staan op `NOT_YET_POLLED`. | Dit is operationeel werk, geen code. |

## 2. Bestanden die worden gewijzigd

- `src/portfolio_cockpit/scoring/drift.py`: wordt de echte Quality Drift-engine. De bestaande functies blijven, zodat de huidige tests blijven slagen.
- `src/portfolio_cockpit/scoring/valuation.py`: wordt de Valuation-engine. `valuation_score_from_weighted_z` blijft bestaan.
- `src/portfolio_cockpit/scoring/portfolio_risk.py`: krijgt scenario's, het label en sectorgewichten. `portfolio_impact` blijft bestaan.
- `src/portfolio_cockpit/config.py`: krijgt validatie voor de nieuwe YAML-bestanden.
- `src/portfolio_cockpit/domain/models.py`: krijgt `DecisionState` en, als dat nodig is, een uitbreiding van `ScoreSnapshot`.
- `config/scoring.yaml`: krijgt verwijzingen naar de nieuwe configuratie.
- `docs/ARCHITECTURE.md`: daar staat "50 = relevant peer median", maar de code gebruikt het gemiddelde. Corrigeren.
- `tests/test_asr_fundamental_quality.py`: verouderde assertie corrigeren (zie §5).
- `.github/workflows/tests.yml`: smoke-tests voor de nieuwe CLI's toevoegen.

## 3. Nieuwe modules en bestanden

- `scoring/drift_pipeline.py`: nulmeting plus observaties geven `normalized_signal` en de drift-score met uitleg per metric.
- `scoring/decision.py`: ADD_CANDIDATE, HOLD, NO_ADD, REVIEW_REDUCE, THESIS_REVIEW en DATA_CHECK. Geen ordervelden.
- `simulation/rebalance.py`: dry-run richting basisgewicht, plus een signal-log met forward-return-evaluatie.
- `dashboard/render.py` en `scripts/build_dashboard.py`: een statische HTML-pagina uit de immutable snapshots.
- Configuratie:
  - `config/quality_drift.yaml`: profielen per bedrijfstype, drempels en full_scale per metric;
  - `config/valuation.yaml`: metrics per type en een lijst `not_applicable`;
  - `config/decision.yaml`: drempels en limieten per positie en sector;
  - `config/risk_scenarios.yaml`.
- `data/drift/`, `data/valuation/` en `data/decisions/`: immutable revisies volgens hetzelfde patroon als `data/scoring/`.

De drift-profielen moeten ook `INSURER_US_P&C` en `FINANCIAL_SERVICES` dekken. De opdracht noemde alleen vier typen; de repo kent er zes.

## 4. Schema- en datamigraties

Er is geen database, en dat is bewust zo. Daarom zijn er geen SQL-migraties. Wel nodig:

- **Nulmetingen:** de huidige JSON-structuur blijft ongewijzigd en wordt alleen gelezen. Een drift-observatie verwijst naar `baseline_path` en de sha256 daarvan. Nieuw: een test die afdwingt dat een eenmaal gecommitte nulmeting nooit verandert (hash vergelijken met `data/baselines/index.json`).
- **Observatieformaat:** `data/observations/<T>/<datum>.json` met provenance per metric (bron, source_type, filing-id, as_of, retrieved_at, raw_value, valuta, periode, calculation_method).
- **Waarderingsinputs:** koers, aantal aandelen en consensus. Hiervoor is een nieuwe databron nodig. Ik stel voor eerst handmatig in te voeren, met provenance, en geen scraping.
- **`schema_version: 1`** voor alle nieuwe outputbestanden.

## 5. Tests vóór en na

**Vóór (nu):** 145 geslaagd, 1 mislukt. De mislukte test is `test_current_scoring_snapshot_blocks_asr`. Hij verwacht dat `capital_strength` bij ASR ontbreekt, maar "Insurer repair v1" heeft dat component juist hersteld. ASR blijft geblokkeerd, alleen om een andere reden. De assertie is verouderd; de code is niet fout. CI op `main` is daardoor waarschijnlijk rood.

**Na:** alle 146 bestaande tests slagen, plus nieuwe tests voor:

- Quality Drift: nulmeting precies 50; een koersbeweging alleen verandert Valuation maar niet de Drift; de nulmeting kan niet overschreven worden.
- Valuation: een verzekeraar gebruikt geen EV/EBITDA of FCF; een pre-revenue bedrijf krijgt geen K/W-interpretatie; een negatieve K/W of EV/EBITDA telt nooit als goedkoop.
- Data Confidence: ontbrekende data geeft `DATA_CHECK`; verouderde data geeft een warning.
- Portfolio Risk: 7% × −30% = −2,1 procentpunt.
- Historie: eerdere scores blijven bewaard.
- Decision Engine: plaatst nooit een order; sector- en positielimieten worden gerespecteerd.

## 6. Voorgestelde volgorde (kleine, losse commits)

1. Verouderde ASR-test corrigeren, zodat CI weer groen is.
2. Quality Drift-engine met configuratie, observaties en immutable revisies.
3. Valuation-engine (eerst met handmatige inputs).
4. Vaste contract-codes voor de Data Confidence-warnings.
5. Portfolio Risk-scenario's en het label.
6. Decision Engine.
7. Dashboard.
8. Simulator en signal-log.

Elke stap wordt een aparte commit, met de bestaande suite groen.

## 7. Operationele punten (geen code)

- De repo is **publiek** en bevat strategische doelgewichten (`config/portfolio.yaml`). Zet hem op privé.
- Monitoring initialiseren: secrets (`COCKPIT_USER_AGENT`, heartbeat) instellen en de eerste poll draaien.
