"""
ingestion/adapters/corestack_adapter.py

Adapter for CoreStack MongoDB exports stored in S3 as .bson.gz files.
Reads operations_governance collection, extracts time-series metrics
for Azure VMs, and normalizes them to the standard schema.

Supported metrics:
    - Percentage CPU → cpu_percent
    - MemoryPercentage → memory_percent
    - Network In/Out → network_percent (averaged)
    - BytesReceived/Sent → network_percent (for App Service)
"""

import gzip
import struct
import logging
import boto3
import bson
import pandas as pd
import numpy as np
from io import BytesIO
from typing import Optional
from ingestion.schema import validate_dataframe

logger = logging.getLogger(__name__)

# S3 config
BUCKET = "proactive-finops-corestack"
GOVERNANCE_KEY = "CoreStack/operations_governance-1/cloud_account_data_collection_daily_updated.bson.gz"

# Metric name mapping: CoreStack → our schema
METRIC_MAP = {
    "Percentage CPU": "cpu_percent",
    "CpuPercentage": "cpu_percent",
    "MemoryPercentage": "memory_percent",
    "Network In": "network_in",
    "Network Out": "network_out",
    "BytesReceived": "network_in",
    "BytesSent": "network_out",
}


def _decode_bson_stream(data: bytes) -> list:
    """
    Decode a raw BSON byte stream into a list of documents.
    Reads documents one at a time to handle large files safely.

    Args:
        data: Raw BSON bytes

    Returns:
        List of decoded document dicts
    """
    docs = []
    offset = 0
    while offset < len(data):
        if offset + 4 > len(data):
            break
        doc_size = struct.unpack('<i', data[offset:offset + 4])[0]
        if doc_size <= 0 or offset + doc_size > len(data):
            break
        doc = bson.decode(data[offset:offset + doc_size])
        docs.append(doc)
        offset += doc_size
    return docs


def _fetch_from_s3(bucket: str, key: str) -> bytes:
    """
    Download and decompress a .bson.gz file from S3.

    Args:
        bucket: S3 bucket name
        key: S3 object key

    Returns:
        Decompressed BSON bytes
    """
    logger.info(f"Fetching s3://{bucket}/{key}")
    s3 = boto3.client("s3")
    response = s3.get_object(Bucket=bucket, Key=key)
    compressed = response["Body"].read()
    with gzip.open(BytesIO(compressed), "rb") as gz:
        data = gz.read()
    logger.info(f"Decompressed {len(data)/1024/1024:.1f} MB")
    return data


def load(resource_id: Optional[str] = None) -> pd.DataFrame:
    """
    Load and normalize CoreStack telemetry data from S3.

    Fetches the operations_governance collection, extracts hourly
    CPU, memory, and network metrics per VM, and returns a normalized
    DataFrame conforming to the standard schema.

    Args:
        resource_id: Optional filter for a specific VM resource ID.
                     If None, returns data for all VMs.

    Returns:
        Normalized DataFrame with columns:
        [timestamp, resource_id, cloud_provider, cpu_percent,
         memory_percent, network_percent, disk_percent, cost_per_hour]

    Raises:
        ValueError: If no usable telemetry records are found
    """
    raw = _fetch_from_s3(BUCKET, GOVERNANCE_KEY)
    docs = _decode_bson_stream(raw)
    logger.info(f"Decoded {len(docs)} documents")

    # Group by resource and timestamp
    records = {}  # (element_id, timestamp) → metric dict

    for doc in docs:
        metric_name = doc.get("metric")
        if metric_name not in METRIC_MAP:
            continue

        element_id = doc.get("element_id", "unknown")
        if resource_id and element_id != resource_id:
            continue

        metric_field = METRIC_MAP[metric_name]
        metric_values = doc.get("metric_value", [])

        for point in metric_values:
            ts = point.get("timeStamp")
            avg = point.get("average", 0.0)
            if ts is None:
                continue

            key = (element_id, ts)
            if key not in records:
                records[key] = {
                    "timestamp": ts,
                    "resource_id": element_id,
                    "cloud_provider": "azure",
                    "cpu_percent": 0.0,
                    "memory_percent": 0.0,
                    "network_in": 0.0,
                    "network_out": 0.0,
                    "disk_percent": 0.0,
                    "cost_per_hour": 0.0,
                }
            records[key][metric_field] = float(avg or 0.0)

    if not records:
        raise ValueError("No usable telemetry records found in CoreStack data")

    df = pd.DataFrame(list(records.values()))

    # Combine network in/out into single network_percent
    # Normalize bytes to 0-100 scale using 99th percentile
    net_combined = df["network_in"] + df["network_out"]
    p99 = net_combined.quantile(0.99)
    if p99 > 0:
        df["network_percent"] = (net_combined / p99 * 100).clip(0, 100)
    else:
        df["network_percent"] = 0.0

    df = df.drop(columns=["network_in", "network_out"])

    logger.info(f"Normalized {len(df)} telemetry records across "
                f"{df['resource_id'].nunique()} resources")

    return validate_dataframe(df)
