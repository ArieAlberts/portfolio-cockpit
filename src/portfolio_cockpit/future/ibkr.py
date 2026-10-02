"""Future IBKR integration.

Phase 1 rules:
- no live connection
- no broker credentials
- no order placement

Phase 2 may implement read-only positions/account data.
Phase 4 may implement execution only after backtest + paper validation.
"""

from portfolio_cockpit.adapters.portfolio import PortfolioAdapter


class IBKRPortfolioAdapter(PortfolioAdapter):
    def positions(self):
        raise NotImplementedError("Reserved for a later phase.")
