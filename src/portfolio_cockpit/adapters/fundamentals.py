from __future__ import annotations

from abc import ABC, abstractmethod
from portfolio_cockpit.domain.models import MetricObservation


class FundamentalDataAdapter(ABC):
    @abstractmethod
    def observations_for(self, ticker: str) -> list[MetricObservation]:
        """Return traceable fundamental observations for a ticker."""
        raise NotImplementedError
