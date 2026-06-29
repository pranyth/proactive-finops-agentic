"""
ingestion/schema.py

Defines the normalized telemetry schema that all data source adapters
must output. This is the contract between the ingestion layer and the
forecasting/decision engines.

By enforcing a single schema, the system remains data-source agnostic —
CoreStack, AWS CloudWatch, and synthetic CSV are interchangeable.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import pandas as pd


REQUIRED_COLUMNS = [
    "timestamp",
    "resource_id",
    "cloud_provider",
    "cpu_percent",
    "memory_percent",
    "network_percent",
    "disk_percent",
    "cost_per_hour",
]

CLOUD_PROVIDERS = {"aws", "azure", "gcp", "synthetic"}


@dataclass
class TelemetryRecord:
    """
    A single normalized telemetry reading from any cloud provider.

    Attributes:
        timestamp: UTC datetime of the reading
        resource_id: Unique identifier for the cloud resource
        cloud_provider: One of 'aws', 'azure', 'gcp', 'synthetic'
        cpu_percent: CPU utilization (0-100)
        memory_percent: Memory utilization (0-100)
        network_percent: Network utilization (0-100)
        disk_percent: Disk utilization (0-100)
        cost_per_hour: Estimated cost in USD per hour
    """
    timestamp: datetime
    resource_id: str
    cloud_provider: str
    cpu_percent: float
    memory_percent: float
    network_percent: float
    disk_percent: float
    cost_per_hour: float = 0.0

    def validate(self) -> bool:
        """Validate that all fields are within expected ranges."""
        assert self.cloud_provider in CLOUD_PROVIDERS, \
            f"Unknown provider: {self.cloud_provider}"
        assert 0 <= self.cpu_percent <= 100, \
            f"CPU out of range: {self.cpu_percent}"
        assert 0 <= self.memory_percent <= 100, \
            f"Memory out of range: {self.memory_percent}"
        assert 0 <= self.network_percent <= 100, \
            f"Network out of range: {self.network_percent}"
        assert 0 <= self.disk_percent <= 100, \
            f"Disk out of range: {self.disk_percent}"
        return True


def validate_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Validate that a DataFrame conforms to the normalized schema.
    Raises ValueError if required columns are missing.

    Args:
        df: DataFrame to validate

    Returns:
        Validated DataFrame with correct dtypes
    """
    missing = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    df["timestamp"] = pd.to_datetime(df["timestamp"])
    for col in ["cpu_percent", "memory_percent", "network_percent",
                "disk_percent", "cost_per_hour"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
        df[col] = df[col].clip(0, 100)

    return df.sort_values("timestamp").reset_index(drop=True)
