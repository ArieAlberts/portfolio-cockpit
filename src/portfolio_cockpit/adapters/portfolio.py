from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class Position:
    ticker: str
    market_value: float
    currency: str
    current_weight: float


class PortfolioAdapter(ABC):
    @abstractmethod
    def positions(self) -> list[Position]:
        raise NotImplementedError
