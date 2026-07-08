# Hybrid Data Strategy

This project uses a hybrid dataset strategy so the demo can look production-grade without making false claims about the source data.

## Dataset Positioning

Use this wording for demos, reports, and papers:

> The prototype evaluates an agentic FinOps workflow using CoreStack-derived VM telemetry, deterministic synthetic enterprise context, and open-source cloud trace-inspired workload/failure patterns. Synthetic fields are explicitly labelled and are not presented as real customer records.

Do not say that the generated inventory, cost, incident, pipeline, or action records are real CoreStack production records. They are reproducible demo records generated from the available telemetry shape.

## Source Categories

| Category | Files | Purpose | Claim Boundary |
|---|---|---|---|
| CoreStack-derived telemetry | `data/augmented_vm_metrics.csv`, `data/vm_tags.json` | VM utilization and app tag foundation | Real or CoreStack-derived base data where available; augmented fields are labelled |
| Synthetic application/DB metrics | `data/db_metrics.csv` | Demonstrates VM-to-application health reasoning | Generated for the capstone scenario |
| Synthetic enterprise context | `data/vm_inventory.csv`, `data/cost_metrics.csv`, `data/incident_history.csv`, `data/action_history.csv`, `data/pipeline_runs.csv` | Adds production-style owner, cost, policy, incident, and operational history | Deterministic synthetic data, not customer records |
| Provenance metadata | `data/data_provenance.csv` | Tracks which datasets are real, synthetic, or pattern-inspired | Required for paper-safe reporting |

## Why More Context Is Needed

Raw VM telemetry can answer first-pass utilization questions, but autonomous FinOps recommendations need more context:

- ownership and application mapping
- production/non-production environment
- business criticality
- approval and shutdown policy
- cost and savings estimates
- incident history
- historical actions and outcomes
- pipeline execution/failure logs

Without these fields, a system can identify idle VMs, but it cannot responsibly recommend shutdowns or explain business impact.

## Generated Enterprise Context

Run this command to regenerate all deterministic context files:

```bash
python tools/generate_enterprise_context.py
```

Generated outputs:

- `data/vm_inventory.csv`
- `data/cost_metrics.csv`
- `data/incident_history.csv`
- `data/action_history.csv`
- `data/pipeline_runs.csv`
- `data/data_provenance.csv`

The generator is deterministic. Given the same base telemetry and tags, it creates the same enterprise context each time.

## Open-Source Trace References

The project does not copy raw rows from these datasets. They are used as scholarly pattern references for what cloud workload, failure, and serverless traces commonly contain.

- Google cluster workload trace analysis: https://arxiv.org/abs/2308.02358
- Alibaba co-located datacenter workload trace case study: https://arxiv.org/abs/1808.02919
- Alibaba workload anomaly analysis: https://arxiv.org/abs/1811.06901
- Huawei long-term production serverless workload characterization: https://arxiv.org/abs/2312.10127
- Huawei serverless trace release repository: https://github.com/sir-lab/data-release
- Workflow Trace Archive paper: https://arxiv.org/abs/1906.07471

## How The Agent Uses This Data

The FinOps Analyst Agent profiles the available dataset before answering a question. It reports:

- dataset types
- row counts
- VM count
- application-tagged VM count
- time range
- available and missing columns
- whether raw CoreStack BSON is required
- source mix from provenance records

For VM shutdown and scale-down questions, the agent uses VM telemetry, inventory, shutdown policy, cost, and application tags. For application degradation questions, it requires DB metrics and app context. For risk questions, it also considers incident history and business criticality.

## Paper-Safe Limitations

Include these limitations if this becomes a paper:

- The current prototype is an agentic decision-support demo, not a deployed autonomous remediation platform.
- Enterprise metadata, cost metrics, incidents, action history, and pipeline runs are synthetic unless replaced by real exports.
- Open-source traces inform workload and failure pattern design, but raw open-source records are not merged into the current dataset.
- Recommendation quality should be validated against real billing, CMDB, incident, and approval data before production use.

## Future Production Data To Request From Vijay

Ask for these fields if Vijay/CoreStack can provide them:

- VM inventory export with SKU, region, subscription, owner, app, environment, and business criticality
- Azure/AWS billing export with daily or hourly VM cost
- Real memory, disk, and network telemetry if current export is incomplete
- Application and DB performance metrics with timestamps
- Incident/ticket history mapped to VM or app
- Past rightsizing/shutdown actions and outcomes
- Pipeline execution logs with status, duration, failure reason, and retries
- Serverless/Lambda execution logs and payload samples
