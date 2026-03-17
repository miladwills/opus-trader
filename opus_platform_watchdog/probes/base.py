"""Base probe interface."""

from __future__ import annotations
from abc import ABC, abstractmethod
from ..models import ProbeResult


class BaseProbe(ABC):
    name: str
    cadence_sec: float
    timeout_sec: float

    @abstractmethod
    async def execute(self) -> ProbeResult:
        ...
