"""Demo Azure adapter backed by CoreStack-derived rows in the multi-cloud dataset."""

from ingestion.adapters.base import MultiCloudCsvAdapter


def load():
    return MultiCloudCsvAdapter("azure").load()
