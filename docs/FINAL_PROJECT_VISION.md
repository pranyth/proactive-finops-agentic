# Final Project Vision

## Project Title

**Agentic FinOps Governance Platform for Multi-Cloud AI and Infrastructure Services**

## One-Line Summary

An event-driven multi-agent FinOps platform that monitors cloud infrastructure and managed AI services, predicts demand, identifies cost and reliability risks, explains recommendations with an LLM, and executes approved remediation through AWS Lambda.

## Problem Being Solved

Cloud teams often pay for resources that are oversized, idle, poorly scheduled, or using an unnecessarily expensive service tier. AI workloads create additional waste through excessive tokens, oversized models, missing prompt caching, low batch utilization, and unused model deployments.

The platform turns telemetry, billing, application context, and incident history into safe and explainable actions. It answers three practical questions:

1. What is being used and how much does it cost?
2. What can be optimized without harming the application?
3. What approved action should be executed, and did it work?

## Main Use Cases

### Infrastructure FinOps

- Find idle or underused VMs.
- Recommend scale up, scale down, smaller SKUs, or scheduled shutdowns.
- Include application ownership, environment, criticality, incidents, and forecast demand.
- Estimate savings and operational risk before any change.

### AI FinOps

- Analyze Amazon Bedrock usage as the primary managed AI service.
- Support Azure OpenAI and Google Vertex AI through a provider-neutral data model.
- Detect expensive model selection, excessive output tokens, missing prompt caching, low batch utilization, and unused deployments.
- Recommend a smaller model, caching, token limits, batching, tier changes, or shutdown of an unused deployment.
- Preserve quality, latency, and business-criticality constraints.

### Operational FinOps

- Monitor pipeline executions, failures, retries, and processing delays.
- Explain why a recommendation was generated.
- Create approval-controlled AWS Lambda remediation payloads.
- Verify the result and maintain a complete audit trail.

## End-to-End Flow

```text
Cloud telemetry, billing, tags and incidents
                    |
                    v
          FastAPI ingestion gateway
                    |
                    v
             Redis event bus
                    |
                    v
       LangGraph Coordinator Agent
                    |
                    v
        Specialized autonomous agents
                    |
                    v
 PostgreSQL + vector knowledge base
                    |
                    v
 Recommendation, evidence and approval
                    |
                    v
        AWS Lambda remediation action
                    |
                    v
 Verification, rollback, audit and dashboard
```

The dashboard does not manually run each agent. It visualizes system state and lets an operator ask questions, review evidence, approve actions, and inspect results.

## Autonomous Agent Responsibilities

| Agent | Responsibility |
|---|---|
| Coordinator Agent | Uses LangGraph to route events, maintain workflow state, checkpoint progress, retry failures, and coordinate agents. |
| Telemetry Agent | Validates and normalizes VM, AI-service, cost, tag, and health events. |
| Dataset Intelligence Agent | Profiles available data, checks quality and provenance, and decides whether required evidence is present. |
| Forecasting Agent | Predicts future utilization, demand, cost, and capacity risk using reusable forecasting logic. |
| AI Service FinOps Agent | Analyzes model, token, cache, latency, quality, and deployment efficiency. |
| Recommendation Agent | Combines forecasts, cost, business context, policies, and incidents into explainable decisions. |
| Pipeline Monitor Agent | Detects pipeline failures, delays, schema errors, and repeated retries. |
| Knowledge Agent | Stores and retrieves historical telemetry, decisions, actions, incidents, and outcomes. |
| Query Agent | Answers natural-language questions using retrieved evidence and structured tools. |
| Serverless Action Agent | Creates, validates, submits, verifies, and audits approved AWS Lambda actions. |

Each independently deployable agent exposes a health/API contract and consumes relevant events. Agents remain active through worker processes instead of being invoked sequentially by the UI.

## How LangGraph And LangChain Are Used

**LangGraph** provides the stateful workflow: agent nodes, conditional edges, retries, failure paths, checkpoints, human approval, and resumable execution.

**LangChain** provides the reasoning layer inside agents:

- an LLM, using a local Ollama model or an approved cloud model;
- role-specific prompts and policy instructions;
- tools for forecasts, SQL queries, cost calculations, policy checks, and Lambda operations;
- a retriever for historical context;
- conversation and workflow memory;
- structured output parsers;
- guardrails that prevent unsupported or unapproved actions.

Existing forecasting and analytics logic remains reusable as agent tools. The LLM selects and explains tools; it does not replace reliable calculations with guesses.

## Recommendation Output

Every decision contains:

- action and affected resource;
- plain-English reasoning;
- supporting telemetry and retrieved evidence;
- confidence score;
- estimated monthly savings;
- business impact and quality risk;
- required approval level;
- proposed Lambda payload;
- correlation ID and audit metadata.

Supported actions include `KEEP_RUNNING`, `SCALE_UP`, `SCALE_DOWN`, `MOVE_TO_SMALLER_SKU`, `SCHEDULE_SHUTDOWN`, `SWITCH_TO_SMALLER_MODEL`, `ENABLE_PROMPT_CACHING`, `REDUCE_OUTPUT_TOKENS`, `BATCH_REQUESTS`, `CHANGE_SERVICE_TIER`, `SHUTDOWN_UNUSED_DEPLOYMENT`, `DB_INVESTIGATION`, `PIPELINE_INVESTIGATION`, `COST_ANOMALY`, and `NO_ACTION`.

## Safe AWS Lambda Automation

AWS Lambda acts as the execution layer, not the decision maker. A production action follows this sequence:

1. The agent creates a recommendation and evidence package.
2. Policy checks determine whether it is advisory, approval-required, or blocked.
3. An authorized operator approves the action when required.
4. The Serverless Action Agent invokes the correct Lambda function.
5. The platform checks the resource after execution.
6. A failed verification triggers retry, rollback, or escalation.
7. The request, approval, response, and outcome are written to the audit trail.

Example functions include VM rightsizing, shutdown scheduling, Bedrock configuration changes, and pipeline alerts. Real remediation is only enabled after credentials, least-privilege IAM roles, approval policies, idempotency, and rollback controls are configured.

## Data And Knowledge Platform

- **PostgreSQL:** structured telemetry, costs, recommendations, approvals, actions, and agent state.
- **pgvector or Qdrant:** searchable history, incidents, explanations, runbooks, and prior outcomes.
- **Redis:** event transport, worker queues, locks, and short-lived state.
- **Object storage:** raw source snapshots and reproducible research datasets.
- **Provenance metadata:** source, license, synthetic-generation method, seed, schema version, and timestamp.

The research dataset combines available CoreStack-derived context, suitable public workload patterns, and clearly labelled synthetic AI-service usage. Synthetic records must never be presented as real customer observations.

## Production Technology Stack

- LangGraph and LangChain for orchestration and reasoning;
- FastAPI for ingestion, agent APIs, queries, and approvals;
- Celery workers with Redis for continuous background execution;
- PostgreSQL with pgvector, or PostgreSQL plus Qdrant;
- scikit-learn and existing analytics code for forecasting;
- Ollama for local demonstrations, with optional OpenAI or Anthropic adapters;
- AWS Lambda for approved remediation;
- Docker and Docker Compose for repeatable deployment;
- a dedicated web dashboard for operations, evidence, approvals, and audit history;
- logs, metrics, traces, health checks, and alerting for observability.

## Final Outcome

The finished system is a cloud optimization control plane rather than a VM-only dashboard. It continuously observes multiple cloud providers and services, reasons over technical and business context, recommends defensible cost actions, automates approved changes, validates their results, and learns from historical outcomes.

## Resume Description

Built an event-driven, multi-agent FinOps governance platform for multi-cloud infrastructure and managed AI services. Used LangGraph and LangChain to coordinate autonomous agents that analyze telemetry, forecasts, billing, application context, and incidents; generate evidence-backed optimization recommendations with local or cloud LLMs; and execute approval-controlled AWS Lambda remediation with verification and audit logging.

### Resume Bullets

- Designed an event-driven multi-agent architecture using LangGraph, LangChain, FastAPI, Redis, PostgreSQL/pgvector, and containerized background workers.
- Developed FinOps analysis for VM rightsizing and managed AI workloads, including model selection, token usage, prompt caching, quality risk, and estimated savings.
- Reused forecasting and analytics logic as deterministic agent tools while using LLM reasoning for tool selection, context retrieval, and explainable answers.
- Designed approval-gated AWS Lambda workflows with policy validation, idempotency, post-action verification, rollback, and end-to-end auditability.
- Built a normalized, provenance-labelled research dataset from enterprise context, public workload patterns, and reproducible synthetic AI-service telemetry.

## Implementation Status And Honest Claims

The current demo already includes FastAPI, SQLite persistence, a background event worker, normalized multi-provider AI-service data, local Ollama inference with `llama3.2:3b`, evidence-backed recommendations, simulated Lambda payloads, and an operational web dashboard.

The following are the **target production architecture** and must not be described as completed until implemented and verified:

- LangChain agent internals;
- LangGraph orchestration and checkpoints;
- Redis/Celery event processing;
- PostgreSQL and a vector knowledge base;
- live cloud-provider telemetry and billing ingestion;
- real AWS Lambda execution, approval, verification, and rollback.

Until then, use the current-demo wording for demonstrations and the final-vision wording only as the stated project goal or work in progress.
