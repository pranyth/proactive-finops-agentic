"""
extract_app_tags.py
Extract VM -> application tag mapping from CoreStack inventory BSON.
Saves data/vm_tags.json for use by DB metrics generator and dashboard.
"""
import gzip, struct, bson, json, pandas as pd

INVENTORY_PATH = "corestack_data/resource_inventory-1/service_resource_inventory_v2_updated.bson.gz"
OUTPUT_PATH    = "data/vm_tags.json"

# Our known VMs
known_vms = set(pd.read_csv("data/augmented_vm_metrics.csv")["resource_id"].unique())

# Tag keys we care about
RELEVANT_KEYS = {"Application", "app", "application", "pod", "App Owner",
                 "Portfolio Owner", "Owner", "department", "Application Name",
                 "role", "Role", "service", "Service", "workload"}

vm_tags = {}

with gzip.open(INVENTORY_PATH, "rb") as f:
    while True:
        size_bytes = f.read(4)
        if len(size_bytes) < 4:
            break
        size = struct.unpack("<i", size_bytes)[0]
        rest = f.read(size - 4)
        try:
            doc = bson.decode(size_bytes + rest)
        except Exception:
            continue

        summary = doc.get("summary_details", {})
        name = summary.get("name", "") if isinstance(summary, dict) else ""
        if not name or name not in known_vms:
            continue

        tags_raw = doc.get("tags", [])
        tags = {}
        if isinstance(tags_raw, list):
            for t in tags_raw:
                if isinstance(t, dict):
                    k = t.get("key", "").strip()
                    v = t.get("value", "").strip()
                    if k and k in RELEVANT_KEYS and v:
                        tags[k] = v

        if name not in vm_tags:
            vm_tags[name] = tags
        else:
            vm_tags[name].update(tags)  # merge if seen multiple times

# Assign application labels
result = {}
for vm, tags in vm_tags.items():
    app = (tags.get("Application") or tags.get("application") or
           tags.get("app") or tags.get("Application Name") or
           tags.get("pod") or "untagged")
    result[vm] = {
        "application": app,
        "app_owner":   tags.get("App Owner", tags.get("Owner", "")),
        "portfolio_owner": tags.get("Portfolio Owner", ""),
        "department":  tags.get("department", ""),
        "raw_tags":    tags,
    }

# VMs not found in inventory get untagged
for vm in known_vms:
    if vm not in result:
        result[vm] = {"application": "untagged", "app_owner": "", "portfolio_owner": "", "department": "", "raw_tags": {}}

with open(OUTPUT_PATH, "w") as f:
    json.dump(result, f, indent=2)

print(f"Saved {len(result)} VM tag records -> {OUTPUT_PATH}")
print("\nApplication distribution:")
from collections import Counter
apps = Counter(v["application"] for v in result.values())
for app, count in apps.most_common():
    print(f"  {app:20s} {count} VMs")

print("\nVMs with real application tags:")
for vm, info in sorted(result.items()):
    if info["application"] != "untagged":
        print(f"  {vm:45s} app={info['application']:8s} owner={info['app_owner']}")
