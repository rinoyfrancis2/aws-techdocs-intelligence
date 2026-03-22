"""
Test api_gateway Lambda in two modes:

  Mode 1 — Direct Lambda invocation (no API Gateway needed):
    python src/lambda/api_gateway/test_local.py

  Mode 2 — Live API Gateway endpoint (after setup_api_gateway.py):
    python src/lambda/api_gateway/test_local.py --live
"""
import json
import sys
import boto3
from dotenv import load_dotenv

load_dotenv()

REGION = "eu-west-1"
FUNCTION = "api_gateway"
QUERIES = [
    "What does the nmap cheatsheet say about SYN scans?",
    "How many documents are indexed?",
    "What does the nmap doc say about port scanning, and when was it indexed?",
]


def invoke_direct(query: str):
    """Invoke Lambda directly — simulates the API Gateway event shape."""
    client = boto3.client("lambda", region_name=REGION)
    payload = {"body": json.dumps({"query": query})}
    response = client.invoke(
        FunctionName=FUNCTION,
        Payload=json.dumps(payload).encode(),
    )
    result = json.loads(response["Payload"].read())
    print(f"\nQuery: {query}")
    if "body" in result:
        body = json.loads(result["body"])
        print(f"Answer: {body.get('answer') or body.get('error')}")
    else:
        print(f"Lambda error: {json.dumps(result, indent=2)}")


def invoke_live(query: str, invoke_url: str):
    """Invoke via live API Gateway HTTP endpoint."""
    import urllib.request

    data = json.dumps({"query": query}).encode()
    req = urllib.request.Request(
        invoke_url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    print(f"\nQuery: {query}")
    with urllib.request.urlopen(req) as resp:
        body = json.loads(resp.read())
        print(f"Answer: {body.get('answer') or body.get('error')}")


if __name__ == "__main__":
    live_mode = "--live" in sys.argv

    if live_mode:
        # Load invoke URL from outputs config written by setup_api_gateway.py
        try:
            with open("outputs/api_gateway_config.json") as f:
                config = json.load(f)
            url = config["invoke_url"]
        except FileNotFoundError:
            print("outputs/api_gateway_config.json not found.")
            print("Run python src/infra/setup_api_gateway.py first.")
            sys.exit(1)

        print(f"=== Live API Gateway test: {url} ===")
        for q in QUERIES:
            invoke_live(q, url)
    else:
        print(f"=== Direct Lambda invocation test ===")
        for q in QUERIES:
            invoke_direct(q)
