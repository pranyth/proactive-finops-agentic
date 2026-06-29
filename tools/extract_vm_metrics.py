"""
tools/extract_vm_metrics.py

Streams the CoreStack BSON file without loading it fully into memory.
Extracts VM metrics and writes directly to a lightweight CSV.
"""

import gzip
import struct
import bson
import csv
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

INPUT = "corestack_data/operations_governance-1/cloud_account_data_collection_daily_updated.bson.gz"
OUTPUT = "data/corestack_vm_metrics.csv"

METRIC_MAP = {
    "Percentage CPU": "cpu_percent",
    "CpuPercentage": "cpu_percent",
    "MemoryPercentage": "memory_percent",
    "Network In": "network_in",
    "Network Out": "network_out",
}

TARGET_CATEGORY = "Virtual_Machines"
CHUNK_SIZE = 4 * 1024 * 1024

def stream_bson_docs(filepath):
    """Stream BSON documents one at a time from a gzip file."""
    buffer = b""
    with gzip.open(filepath, "rb") as gz:
        while True:
            chunk = gz.read(CHUNK_SIZE)
            if not chunk:
                break
            buffer += chunk
            offset = 0
            while offset + 4 <= len(buffer):
                doc_size = struct.unpack('<i', buffer[offset:offset+4])[0]
                if doc_size <= 0:
                    offset += 1
                    continue
                if offset + doc_size > len(buffer):
                    break
                doc = bson.decode(buffer[offset:offset+doc_size])
                yield doc
                offset += doc_size
            buffer = buffer[offset:]

def extract():
    logger.info("Streaming BSON file...")
    records = {}
    doc_count = 0
    vm_docs = 0

    for doc in stream_bson_docs(INPUT):
        doc_count += 1
        if doc_count % 10000 == 0:
            logger.info(f"Processed {doc_count} docs, {vm_docs} VM metric docs")

        if doc.get("category") != TARGET_CATEGORY:
            continue

        metric_name = doc.get("metric")
        if metric_name not in METRIC_MAP:
            continue

        vm_docs += 1
        element_id = doc.get("element_id", "unknown")
        vm_name = element_id.split("/")[-1] if "/" in element_id else element_id
        metric_field = METRIC_MAP[metric_name]

        for point in doc.get("metric_value", []):
            ts = point.get("timeStamp")
            avg = point.get("average", 0.0)
            if ts is None:
                continue

            key = (vm_name, str(ts))
            if key not in records:
                records[key] = {
                    "timestamp": ts,
                    "resource_id": vm_name,
                    "cloud_provider": "azure",
                    "cpu_percent": 0.0,
                    "memory_percent": 0.0,
                    "network_in": 0.0,
                    "network_out": 0.0,
                    "disk_percent": 0.0,
                    "cost_per_hour": 0.0,
                }
            records[key][metric_field] = float(avg or 0.0)

    logger.info(f"Total docs: {doc_count}, VM metric docs: {vm_docs}")
    logger.info(f"Writing {len(records)} records to CSV...")

    with open(OUTPUT, "w", newline="") as csvfile:
        writer = None
        for i, (key, row) in enumerate(records.items()):
            net = row.pop("network_in", 0.0) + row.pop("network_out", 0.0)
            row["network_percent"] = net
            if i == 0:
                writer = csv.DictWriter(csvfile, fieldnames=list(row.keys()))
                writer.writeheader()
            writer.writerow(row)

    logger.info(f"Done. Output: {OUTPUT}")

if __name__ == "__main__":
    extract()
