"""
Quick test: invoke data_query Lambda directly via AWS CLI-style boto3 call.
Run from project root: python src/lambda/data_query/test_local.py
Requires .env to be loaded (or env vars set).
"""
import os
import json
import boto3
from dotenv import load_dotenv

load_dotenv()

client = boto3.client("lambda", region_name="eu-west-1")
FUNCTION = "data_query"


def invoke(query_type: str, doc_name: str = ""):
    # Simulate a Bedrock Agent Action Group event
    properties = [{"name": "query_type", "value": query_type}]
    if doc_name:
        properties.append({"name": "doc_name", "value": doc_name})

    payload = {
        "actionGroup": "data-query",
        "apiPath": "/query",
        "httpMethod": "POST",
        "requestBody": {
            "content": {
                "application/json": {
                    "properties": properties
                }
            }
        }
    }
    response = client.invoke(
        FunctionName=FUNCTION,
        Payload=json.dumps(payload).encode()
    )
    result = json.loads(response["Payload"].read())
    body = json.loads(result["response"]["responseBody"]["application/json"]["body"])
    print(f"\n--- {query_type} ({doc_name or 'n/a'}) ---")
    print(json.dumps(body, indent=2))


if __name__ == "__main__":
    invoke("count_docs")
    invoke("list_docs")
    invoke("doc_status", "nmap")
    invoke("doc_status", "nonexistent-doc")
