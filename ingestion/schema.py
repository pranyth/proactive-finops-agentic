"""Normalized telemetry schema for provider-agnostic FinOps ingestion.

This module keeps the legacy VM metric contract used by the original notebooks
and dashboards, and adds a richer multi-cloud schema used by the FastAPI
command-center demo.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

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

MULTICLOUD_REQUIRED_COLUMNS = [
    "timestamp",
    "provider",
    "source_system",
    "account_id",
    "region",
    "resource_id",
    "normalized_resource_id",
    "resource_type",
    "instance_type",
    "cpu_percent",
    "memory_percent",
    "network_percent",
    "disk_percent",
    "cost_per_hour",
    "application",
    "environment",
    "business_criticality",
    "workload_class",
    "schema_version",
    "source_type",
]

CLOUD_PROVIDERS = {"aws", "azure", "gcp", "synthetic"}
RESOURCE_TYPES = {"virtual_machine", "serverless_function", "database", "pipeline"}
SCHEMA_VERSION = "finops.telemetry.v1"


@dataclass
class TelemetryRecord:
    """Legacy normalized VM telemetry reading from any cloud provider."""

    timestamp: datetime
    resource_id: str
    cloud_provider: str
    cpu_percent: float
    memory_percent: float
    network_percent: float
    disk_percent: float
    cost_per_hour: float = 0.0

    def validate(self) -> bool:
        assert self.cloud_provider in CLOUD_PROVIDERS, f"Unknown provider: {self.cloud_provider}"
        for field_name in ["cpu_percent", "memory_percent", "network_percent", "disk_percent"]:
            value = getattr(self, field_name)
            assert 0 <= value <= 100, f"{field_name} out of range: {value}"
        return True


@dataclass
class MultiCloudTelemetryRecord:
    """Provider-neutral telemetry contract used by the agentic platform."""

    timestamp: datetime
    provider: str
    source_system: str
    account_id: str
    region: str
    resource_id: str
    normalized_resource_id: str
    resource_type: str
    instance_type: str
    cpu_percent: float
    memory_percent: float
    network_percent: float
    disk_percent: float
    cost_per_hour: float
    application: str
    environment: str
    business_criticality: str
    workload_class: str
    schema_version: str = SCHEMA_VERSION
    source_type: str = "unknown"
    tags: dict[str, Any] | None = None


def validate_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Validate the legacy telemetry schema used by older dashboards."""
    missing = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    df = df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    for col in ["cpu_percent", "memory_percent", "network_percent", "disk_percent", "cost_per_hour"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0).clip(0, 100)

    return df.sort_values("timestamp").reset_index(drop=True)


def validate_multicloud_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Validate the provider-neutral multi-cloud telemetry schema."""
    missing = [col for col in MULTICLOUD_REQUIRED_COLUMNS if col not in df.columns]
    if missing:
        raise ValueError(f"Missing multi-cloud telemetry columns: {missing}")

    df = df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    for col in ["cpu_percent", "memory_percent", "network_percent", "disk_percent", "cost_per_hour"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0).clip(lower=0)
    for col in ["cpu_percent", "memory_percent", "network_percent", "disk_percent"]:
        df[col] = df[col].clip(upper=100)
    df["provider"] = df["provider"].str.lower()
    unknown = sorted(set(df["provider"].dropna()) - CLOUD_PROVIDERS)
    if unknown:
        raise ValueError(f"Unknown provider labels: {unknown}")
    df["schema_version"] = df["schema_version"].fillna(SCHEMA_VERSION)
    return df.sort_values(["provider", "resource_id", "timestamp"]).reset_index(drop=True)
