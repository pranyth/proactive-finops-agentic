"""Demo GCP adapter backed by the generated multi-cloud dataset."""

from ingestion.adapters.base import MultiCloudCsvAdapter


def load():
    return MultiCloudCsvAdapter("gcp").load()
