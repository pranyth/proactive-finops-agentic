"""Base adapter contract for multi-cloud telemetry providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from ingestion.schema import validate_multicloud_dataframe


@dataclass(frozen=True)
class AdapterMetadata:
    provider: str
    source_system: str
    description: str


class TelemetryAdapter(ABC):
    """Provider adapter boundary: extract, normalize, validate."""

    metadata: AdapterMetadata

    @abstractmethod
    def extract(self) -> pd.DataFrame:
        """Read provider-specific raw or demo data."""

    @abstractmethod
    def normalize(self, raw: pd.DataFrame) -> pd.DataFrame:
        """Convert provider-specific input into the common telemetry schema."""

    def load(self) -> pd.DataFrame:
        return validate_multicloud_dataframe(self.normalize(self.extract()))


class MultiCloudCsvAdapter(TelemetryAdapter):
    """Adapter for the generated multi-cloud demo dataset."""

    def __init__(self, provider: str, path: str | Path = "data/multicloud_vm_metrics.csv") -> None:
        self.provider = provider.lower()
        self.path = Path(path)
        self.metadata = AdapterMetadata(
            provider=self.provider,
            source_system=f"{self.provider}_demo_csv",
            description="Generated multi-cloud telemetry rows in the common schema.",
        )

    def extract(self) -> pd.DataFrame:
        df = pd.read_csv(self.path, parse_dates=["timestamp"])
        return df[df["provider"].str.lower() == self.provider].copy()

    def normalize(self, raw: pd.DataFrame) -> pd.DataFrame:
        return raw
