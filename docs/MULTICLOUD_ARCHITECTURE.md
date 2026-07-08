# Multi-Cloud Architecture

## Project Title

**Agentic Proactive FinOps Governance for Multi-Cloud Telemetry**

## Core Idea

CoreStack is the first telemetry source, not the platform boundary. The platform normalizes provider data into one common telemetry schema before events, agents, recommendations, and action workflows run.

```text
CoreStack / Azure Monitor / AWS CloudWatch / GCP Monitoring / CSV exports
        ->
Provider Adapters
        ->
Common Multi-Cloud Telemetry Schema
        ->
SQLite Event Bus
        ->
Coordinator Agent
        ->
FinOps Analyst Agent + internal tools
        ->
Recommendations + event stream + serverless action logs
```

## Current Evaluation Data

The checked-in demo currently uses:

- Azure/CoreStack-derived VM telemetry from `data/augmented_vm_metrics.csv`
- deterministic AWS/GCP telemetry rows in `data/multicloud_vm_metrics.csv`
- open-source workload trace pattern references in `data/open_trace_patterns.csv`
- synthetic enterprise/cost/incident/action context for FinOps realism

The AWS/GCP rows are not raw public cloud trace rows. They are generated from cited trace-pattern references and explicitly labelled as synthetic.

## Common Schema

The normalized schema includes:

- `timestamp`
- `provider`
- `source_system`
- `account_id`
- `region`
- `resource_id`
-
ormalized_resource_id`
- `resource_type`
- `instance_type`
- `cpu_percent`
- `memory_percent`
-
etwork_percent`
- `disk_percent`
- `cost_per_hour`
- `application`
- `environment`
- `business_criticality`
- `workload_class`
- `schema_version`
- `source_type`

## Adapter Boundary

Adapters expose the same lifecycle:

```text
extract provider data -> normalize to common schema -> validate schema
```

Current adapter files:

- `ingestion/adapters/corestack_adapter.py`
- `ingestion/adapters/cloudwatch_adapter.py`
- `ingestion/adapters/csv_adapter.py`
- `ingestion/adapters/aws_demo_adapter.py`
- `ingestion/adapters/azure_demo_adapter.py`
- `ingestion/adapters/gcp_demo_adapter.py`

## Paper-Safe Claim

Use this wording:

> The prototype is evaluated on a hybrid multi-cloud dataset containing CoreStack-derived Azure telemetry, deterministic synthetic enterprise context, and AWS/GCP telemetry generated from cited open-source cloud workload trace patterns. All synthetic and pattern-inspired fields are explicitly labelled through provenance metadata.
