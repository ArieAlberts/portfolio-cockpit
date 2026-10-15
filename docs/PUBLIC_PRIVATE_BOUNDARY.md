# Separate the public Portfolio Cockpit from the local IBKR dashboard

Status: proposed repair, 2026-10-13. **This PR does not activate live
broker connectivity, refresh market quotes, or merge the 10 October market
update.** The GitHub Pages site continues to be read-only research.

## Two distinct products

| | Public: GitHub Pages `portfolio-cockpit` | Local/private: IBKR monitor |
|---|---|---|
| Audience | Public | Account owner |
| Data | Public company metrics, audited price/valuation snapshots, historic research | Read-only actual positions, quantity, balances, margin, exposure, NLV |
| Runtime | Stateless static GitHub Pages build | Owner-controlled computer or private service |
| Credentials | None | Stored **only** in a private local credential manager |
| Storage | Public immutable `data/market`, `data/valuation`, `data/scoring` | Private, non-versioned broker snapshot storage |
| Risk | Public company/valuation research; no individual trades | Read-only position/rebalance planning; no live orders |
| Refresh | Market imports require a separate verified provider; filings monitoring runs daily | Authenticated broker read-only fetch on local machine |

**Current defect:** An account snapshot dated 2026-10-04 was committed to the
public repository and displayed on GitHub Pages; meanwhile a daily source
monitor was mistaken for a broker/quote refresh. `config/positions.yaml`
contains a manually imported portfolio. The latest decision pointers refer
to 2026-10-05. A 2026-10-10 market update exists in an **unmerged** PR (#27);
its unresolved quote and peer-data verification items must be addressed
before publishing new investment signals.

## Immediate repair in this branch

1. Public HTML does not include the broker's NLV, cash, positions or CFD sizes.
2. Each dashboard build checks real source dates, not only workflow status.
3. Stale positions/decision inputs suppress current weights, gap, risk
   scenarios and actionable state labels; stale price data suppress
   price-dependent valuation labels; peer alerts remain withheld if stale.
4. GitHub Pages is rebuilt daily so stale-data warnings remain accurate even
   when no new data arrive.
5. Neither scores nor Fundamental Quality/Quality Drift baselines are changed,
   and the permanent no-live-execution invariant is retained.

## Work still needed before automated syncing can be enabled

1. Identify and inspect the *local* dashboard code/runtime and data path.
   It is **not** a second repository in the owner's currently accessible
   GitHub account; it may be on another machine.
2. Implement a read-only IBKR importer within the **private/local** runtime,
   using local credential storage. Never place an IBKR token, account number,
   raw positions or account-value snapshot into public Git, artifacts or
   log output.
3. Validate currencies (base EUR vs USD/DKK), `market_value` versus CFD
   notional, cash/NLV/positions reconciliation, and authoritative snapshot
   timestamps; reject partial and incompatible imports.
4. Select and license a reliable market-price source covering EU/UK/US
   exchanges. Attach source, trading currency, price timestamp, age and
   retrieval time per instrument. Market quote refresh is not identical to
   company filings monitoring.
5. Schedule the read-only local import and valuations separately, with
   explicit failure states, source-date-based staleness and reconciliation.
6. Decide which *non-sensitive*, aggregated information—if any—may safely
   flow from the private system to the public research dashboard.
7. Audit the existing public Git history for published broker account data.
   Deleting a tracked file from the working tree does **not** erase history;
   history remediation needs a separate, carefully reviewed operation.

## Separate review of 10 October inputs

See PR #27. It contains market data for 23 monitored stocks, but some prices
were not independently verified; a peer-market refresh was blocked by a
DNS issue. **Do not merge it just to change the date on the dashboard.**

## Verification

- Run the full deterministic test suite in GitHub Actions on this branch.
- Verify public HTML contains no broker account amounts or quantities and
  clearly marks historical decisions as stale.
- Verify tested fresh input fixtures still render legitimate decision states.
- Review public/private separation before merging.
