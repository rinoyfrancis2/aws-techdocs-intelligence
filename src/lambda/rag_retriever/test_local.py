"""
Local test for rag_retriever — runs handler directly without deploying.
Requires: .env loaded, VPN/direct RDS access OR run from inside the VPC.

Usage (from project root):
    python -m dotenv run -- python src/lambda/rag_retriever/test_local.py
"""
import os
import sys
import json

# Add Lambda dir to path so handler can be imported
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

import handler  # noqa: E402

# Simulate a Bedrock Agent Action Group event
test_event = {
    "messageVersion": "1.0",
    "agent": {"name": "RAGAgent", "id": "test", "alias": "test", "version": "1"},
    "inputText": "What are common nmap scan flags?",
    "sessionId": "test-session-001",
    "actionGroup": "rag-search",
    "apiPath": "/retrieve",
    "httpMethod": "POST",
    "parameters": [],
    "requestBody": {
        "content": {
            "application/json": {
                "properties": [
                    {"name": "query", "type": "string", "value": "What are common nmap scan flags?"},
                    {"name": "top_k", "type": "integer", "value": "3"},
                ]
            }
        }
    },
}

print("=== Invoking rag_retriever locally ===")
response = handler.handler(test_event, None)
print("\n=== Response ===")
print(json.dumps(response, indent=2))

# Parse and display results cleanly
body = json.loads(response["response"]["responseBody"]["application/json"]["body"])
print(f"\n=== Top {len(body.get('results', []))} chunks ===")
for i, r in enumerate(body.get("results", []), 1):
    print(f"\n[{i}] {r['doc_name']} chunk {r['chunk_index']} (score: {r['score']})")
    print(r["content"][:300])
