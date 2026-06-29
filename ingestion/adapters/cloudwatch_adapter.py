"""
ingestion/adapters/cloudwatch_adapter.py

Adapter for AWS CloudWatch metrics.
Pulls real-time EC2 instance metrics directly from the
CloudWatch API using boto3.

Currently implemented as a stub — ready for activation
when EC2 instances are available.
"""

import logging
import pandas as pd
import boto3
from datetime import datetime, timedelta
from ingestion.schema import validate_dataframe

logger = logging.getLogger(__name__)


def load(instance_id: str,
         hours_back: int = 24,
         region: str = "ap-south-1") -> pd.DataFrame:
    """
    Load EC2 metrics from AWS CloudWatch.

    Args:
        instance_id: EC2 instance ID (e.g. 'i-0abc123')
        hours_back: How many hours of history to fetch
        region: AWS region

    Returns:
        Normalized DataFrame conforming to the standard schema

    Raises:
        NotImplementedError: Until EC2 instances are provisioned
    """
    raise NotImplementedError(
        "CloudWatch adapter is ready but requires an active EC2 instance. "
        "Provision an instance and set instance_id to activate."
    )
