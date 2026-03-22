import os
import boto3

AWS_REGION = os.environ.get("AWS_REGION", "eu-west-1")


def get_bedrock_runtime():
    return boto3.client("bedrock-runtime", region_name=AWS_REGION)


def get_bedrock_agent_runtime():
    return boto3.client("bedrock-agent-runtime", region_name=AWS_REGION)


def get_bedrock_agent():
    return boto3.client("bedrock-agent", region_name=AWS_REGION)
