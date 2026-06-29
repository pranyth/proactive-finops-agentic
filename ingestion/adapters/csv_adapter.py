"""
ingestion/adapters/csv_adapter.py

Adapter for synthetic CSV telemetry data.
Acts as a fallback when real cloud data is unavailable,
and is used for local development and testing.

Expected CSV columns:
    timestamp, cpu_percent, memory_percent,
    network_percent, disk_percent
"""

import logging
import pandas as pd
from ingestion.schema import validate_dataframe

logger = logging.getLogger(__name__)


def load(filepath: str,
         resource_id: str = "synthetic-vm-01",
         cloud_provider: str = "synthetic") -> pd.DataFrame:
    """
    Load and normalize a synthetic CSV telemetry file.

    Args:
        filepath: Path to the CSV file
        resource_id: Resource ID to assign to all records
        cloud_provider: Cloud provider label

    Returns:
        Normalized DataFrame conforming to the standard schema

    Raises:
        FileNotFoundError: If the CSV file does not exist
    """
    logger.info(f"Loading CSV from {filepath}")
    df = pd.read_csv(filepath, parse_dates=["timestamp"])

    df["resource_id"] = resource_id
    df["cloud_provider"] = cloud_provider

    if "disk_percent" not in df.columns:
        df["disk_percent"] = 0.0
    if "cost_per_hour" not in df.columns:
        df["cost_per_hour"] = 0.0

    logger.info(f"Loaded {len(df)} records from CSV")
    return validate_dataframe(df)
