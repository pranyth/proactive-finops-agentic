# AI FinOps Dataset and Research Provenance

## Scope

The primary experiment studies FinOps decisions for managed LLM inference, with Amazon Bedrock as the main service. Azure OpenAI and Vertex AI demonstrate that the schema is provider-neutral.

CoreStack did not provide AI invocation or billing records. The project does not claim otherwise.

## Data Construction

The generated dataset uses four explicitly separated inputs:

1. CoreStack-derived context: existing cloud/application context already present in the project.
2. Open-source workload reference: Microsoft Azure Public Dataset LLM inference traces, which contain request timing and input/output token patterns.
3. Official schema reference: Amazon Bedrock CloudWatch metrics for invocations, latency, input/output tokens, cache tokens, client/server errors and throttles.
4. Synthetic business scenarios: provider, model, deployment, budget, criticality, quality and cost scenarios generated with seed `42`.

The synthetic generator creates 30 days of hourly records in normalized SQLite tables. It does not copy public trace rows into a fake customer bill. It derives reproducible workload shapes and labels every generated record as `synthetic_from_open_trace_patterns`.

## Relational Structure

```text
cloud providers -> AI services -> models -> deployments
                                      |          |
                               applications   usage events -> cost records
                                      |          |
                                   incidents  recommendations -> Lambda actions
```

## Research Rules

- Report synthetic and original data separately.
- Treat included token rates as illustrative reference rates, not an invoice.
- Publish the generator seed and scenario configuration.
- Evaluate recommendation precision, savings estimate, quality-floor violations and explanation consistency.
- Never include raw prompts or customer content.

## Primary References

- Microsoft Azure Public Dataset: https://github.com/Azure/AzurePublicDataset
- Amazon Bedrock runtime metrics: https://docs.aws.amazon.com/bedrock/latest/userguide/monitoring-runtime-metrics.html
- Amazon Bedrock pricing reference: https://aws.amazon.com/bedrock/pricing/

