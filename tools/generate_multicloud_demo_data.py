"""Generate provider-neutral multi-cloud telemetry for the FinOps platform.

The output combines:
- CoreStack-derived Azure telemetry already present in augmented_vm_metrics.csv
- deterministic AWS/GCP rows shaped by public cloud workload-trace patterns
- explicit provenance labels for paper-safe reporting

No raw open-source trace rows are copied into the repository. Public traces are
used as pattern references for workload shape, burstiness, and failure context.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ingestion.schema import SCHEMA_VERSION, validate_multicloud_dataframe

DATA_DIR = Path("data")
VM_METRICS = DATA_DIR / "augmented_vm_metrics.csv"
INVENTORY = DATA_DIR / "vm_inventory.csv"
COST = DATA_DIR / "cost_metrics.csv"
PROVENANCE = DATA_DIR / "data_provenance.csv"
OUT_MULTI = DATA_DIR / "multicloud_vm_metrics.csv"
OUT_PATTERNS = DATA_DIR / "open_trace_patterns.csv"

OPEN_TRACE_PATTERNS = [
    {
        "pattern_id": "google-cluster-bursty-batch",
        "trace_reference": "Google Cluster Trace analysis",
        "citation_url": "https://arxiv.org/abs/2308.02358",
        "provider_model": "gcp",
        "workload_pattern": "bursty_batch_compute",
        "cpu_multiplier": 1.28,
        "memory_multiplier": 1.12,
        "network_multiplier": 1.08,
        "failure_rate_hint": 0.035,
        "source_type": "open_source_trace_pattern_reference",
    },
    {
        "pattern_id": "alibaba-colocated-variable",
        "trace_reference": "Alibaba co-located datacenter workload trace",
        "citation_url": "https://arxiv.org/abs/1808.02919",
        "provider_model": "aws",
        "workload_pattern": "colocated_variable_service",
        "cpu_multiplier": 1.15,
        "memory_multiplier": 1.22,
        "network_multiplier": 1.05,
        "failure_rate_hint": 0.045,
        "source_type": "open_source_trace_pattern_reference",
    },
    {
        "pattern_id": "alibaba-anomaly-spike",
        "trace_reference": "Alibaba workload anomaly analysis",
        "citation_url": "https://arxiv.org/abs/1811.06901",
        "provider_model": "aws",
        "workload_pattern": "anomaly_spike_service",
        "cpu_multiplier": 1.42,
        "memory_multiplier": 1.18,
        "network_multiplier": 1.25,
        "failure_rate_hint": 0.065,
        "source_type": "open_source_trace_pattern_reference",
    },
    {
        "pattern_id": "huawei-serverless-diurnal",
        "trace_reference": "Huawei production serverless workload trace",
        "citation_url": "https://arxiv.org/abs/2312.10127",
        "provider_model": "gcp",
        "workload_pattern": "serverless_diurnal_support",
        "cpu_multiplier": 0.92,
        "memory_multiplier": 0.88,
        "network_multiplier": 1.35,
        "failure_rate_hint": 0.025,
        "source_type": "open_source_trace_pattern_reference",
    },
]

REGIONS = {
    "azure": ["eastus", "westus2", "centralindia", "westeurope"],
    "aws": ["us-east-1", "us-west-2", "ap-south-1", "eu-west-1"],
    "gcp": ["us-central1", "us-east1", "asia-south1", "europe-west1"],
}

INSTANCE_TYPES = {
    "azure": {
        "truly_idle": "Standard_B1s",
        "low_variable": "Standard_B2s",
        "moderate": "Standard_D2s_v5",
        "production": "Standard_D4s_v5",
    },
    "aws": {
        "truly_idle": "t3.micro",
        "low_variable": "t3.small",
        "moderate": "m6i.large",
        "production": "m6i.xlarge",
    },
    "gcp": {
        "truly_idle": "e2-micro",
        "low_variable": "e2-small",
        "moderate": "n2-standard-2",
        "production": "n2-standard-4",
    },
}

HOURLY_COST = {
    "Standard_B1s": 0.012,
    "Standard_B2s": 0.046,
    "Standard_D2s_v5": 0.096,
    "Standard_D4s_v5": 0.192,
    "t3.micro": 0.0104,
    "t3.small": 0.0208,
    "m6i.large": 0.096,
    "m6i.xlarge": 0.192,
    "e2-micro": 0.0084,
    "e2-small": 0.0168,
    "n2-standard-2": 0.097,
    "n2-standard-4": 0.194,
}


def stable_int(value: str, modulo: int) -> int:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return int(digest[:12], 16) % modulo


def provider_for_vm(vm: str) -> str:
    bucket = stable_int(vm + "provider", 10)
    if bucket < 5:
        return "azure"
    if bucket < 8:
        return "aws"
    return "gcp"


def choose(value: str, items: list[str]) -> str:
    return items[stable_int(value, len(items))]


def account_id(provider: str, vm: str) -> str:
    suffix = 100000 + stable_int(provider + vm, 899999)
    if provider == "azure":
        return f"sub-corestack-{suffix}"
    if provider == "aws":
        return f"aws-acct-{suffix}"
    return f"gcp-project-{suffix}"


def normalize_resource_id(provider: str, vm: str) -> str:
    safe = vm.lower().replace("_", "-").replace(" ", "-")
    if provider == "aws":
        return f"arn:aws:ec2:::instance/i-{stable_int(vm, 10**12):012d}"
    if provider == "gcp":
        return f"projects/demo/zones/global/instances/{safe}"
    return f"/subscriptions/demo/resourceGroups/rg-demo/providers/Microsoft.Compute/virtualMachines/{safe}"


def pattern_for(provider: str, vm: str) -> dict:
    candidates = [row for row in OPEN_TRACE_PATTERNS if row["provider_model"] == provider]
    if not candidates:
        return {
            "pattern_id": "corestack-azure-derived",
            "workload_pattern": "corestack_azure_vm",
            "cpu_multiplier": 1.0,
            "memory_multiplier": 1.0,
            "network_multiplier": 1.0,
            "failure_rate_hint": 0.02,
            "citation_url": "internal_corestack_demo",
            "trace_reference": "CoreStack-derived telemetry",
        }
    return candidates[stable_int(vm + "pattern", len(candidates))]


def source_type_for(provider: str) -> str:
    if provider == "azure":
        return "corestack_derived_normalized_multicloud_schema"
    return "open_source_trace_pattern_inspired_synthetic_telemetry"


def build_multicloud() -> pd.DataFrame:
    vm_df = pd.read_csv(VM_METRICS, parse_dates=["timestamp"])
    inventory = pd.read_csv(INVENTORY) if INVENTORY.exists() else pd.DataFrame()
    inv = inventory.set_index("resource_id").to_dict("index") if "resource_id" in inventory else {}

    rows = []
    for vm, group in vm_df.groupby("resource_id", sort=False):
        provider = provider_for_vm(vm)
        info = inv.get(vm, {})
        workload = str(group["workload_class"].iloc[0])
        pattern = pattern_for(provider, vm)
        instance = INSTANCE_TYPES[provider].get(workload, INSTANCE_TYPES[provider]["low_variable"])
        region = choose(provider + vm + "region", REGIONS[provider])
        application = info.get("application", "untagged")
        environment = info.get("environment", "prod" if workload == "production" else "dev")
        criticality = info.get("business_criticality", "high" if environment == "prod" else "low")
        source_type = source_type_for(provider)
        trace_reference = pattern.get("trace_reference", "CoreStack-derived telemetry")
        citation = pattern.get("citation_url", "internal_corestack_demo")
        sample = group.copy()
        if provider != "azure":
            sample = sample.sample(frac=0.45, random_state=stable_int(vm + provider, 999999)).sort_values("timestamp")

        for _, row in sample.iterrows():
            cpu = min(100.0, max(0.0, float(row["cpu_percent"]) * float(pattern["cpu_multiplier"])))
            memory = min(100.0, max(0.0, float(row["memory_percent"]) * float(pattern["memory_multiplier"])))
            network = min(100.0, max(0.0, float(row["network_percent"]) * float(pattern["network_multiplier"])))
            disk = min(100.0, max(0.0, float(row["disk_percent"])))
            rows.append({
                "timestamp": row["timestamp"],
                "provider": provider,
                "source_system": "corestack" if provider == "azure" else f"{provider}_open_trace_pattern_demo",
                "account_id": account_id(provider, vm),
                "region": region,
                "resource_id": f"{provider}-{vm}",
                "normalized_resource_id": normalize_resource_id(provider, vm),
                "resource_type": "virtual_machine",
                "instance_type": instance,
                "cpu_percent": round(cpu, 4),
                "memory_percent": round(memory, 4),
                "network_percent": round(network, 4),
                "disk_percent": round(disk, 4),
                "cost_per_hour": HOURLY_COST[instance],
                "application": application,
                "environment": environment,
                "business_criticality": criticality,
                "workload_class": workload,
                "schema_version": SCHEMA_VERSION,
                "source_type": source_type,
                "open_source_trace_reference": trace_reference,
                "citation_url": citation,
                "telemetry_origin": "corestack_base_pattern" if provider == "azure" else "synthetic_from_public_trace_pattern",
            })
    return validate_multicloud_dataframe(pd.DataFrame(rows))


def update_provenance() -> None:
    rows = []
    if PROVENANCE.exists():
        rows = pd.read_csv(PROVENANCE).to_dict("records")
    additions = [
        {
            "dataset": "open_trace_patterns.csv",
            "fields": "pattern_id, trace_reference, workload_pattern, multipliers, citation_url",
            "source_type": "open_source_trace_pattern_reference",
            "notes": "Cited public cloud traces used as pattern references; raw records are not copied.",
        },
        {
            "dataset": "multicloud_vm_metrics.csv",
            "fields": "provider, source_system, account_id, region, resource_id, instance_type, utilization, cost_per_hour, source_type",
            "source_type": "corestack_derived + open_source_trace_pattern_inspired_synthetic_telemetry",
            "notes": "Provider-neutral schema with Azure/CoreStack-derived rows and AWS/GCP rows generated from public trace patterns.",
        },
    ]
    existing = {row.get("dataset") for row in rows}
    rows.extend(row for row in additions if row["dataset"] not in existing)
    pd.DataFrame(rows).to_csv(PROVENANCE, index=False)


def main() -> None:
    patterns = pd.DataFrame(OPEN_TRACE_PATTERNS)
    multi = build_multicloud()
    patterns.to_csv(OUT_PATTERNS, index=False)
    multi.to_csv(OUT_MULTI, index=False)
    update_provenance()
    print(f"wrote {OUT_PATTERNS}: {len(patterns):,} rows")
    print(f"wrote {OUT_MULTI}: {len(multi):,} rows")
    print("provider counts:")
    print(multi["provider"].value_counts().to_string())


if __name__ == "__main__":
    main()
