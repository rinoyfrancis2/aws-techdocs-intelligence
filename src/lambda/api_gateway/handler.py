"""
Lambda: api_gateway
Triggered by API Gateway POST /query
Flow: parse request → invoke Supervisor Bedrock Agent → return final answer
"""
import os
import json
import uuid
import boto3

REGION = os.environ.get("AWS_REGION", "eu-west-1")
SUPERVISOR_AGENT_ID = os.environ["SUPERVISOR_AGENT_ID"]
SUPERVISOR_AGENT_ALIAS_ID = os.environ["SUPERVISOR_AGENT_ALIAS_ID"]

# bedrock-agent-runtime is the client for invoking agents (not bedrock-runtime)
bedrock_agent = boto3.client("bedrock-agent-runtime", region_name=REGION)


def invoke_supervisor(query: str) -> str:
    # Each conversation needs a unique session ID.
    # For stateless single-turn queries we generate one per request.
    session_id = str(uuid.uuid4())

    response = bedrock_agent.invoke_agent(
        agentId=SUPERVISOR_AGENT_ID,
        agentAliasId=SUPERVISOR_AGENT_ALIAS_ID,
        sessionId=session_id,
        inputText=query,
    )

    # invoke_agent returns a streaming EventStream — we must consume it fully.
    # Chunks arrive as 'chunk' events inside 'completion'; concatenate them all.
    full_answer = ""
    for event in response["completion"]:
        if "chunk" in event:
            full_answer += event["chunk"]["bytes"].decode("utf-8")

    return full_answer.strip()


def handler(event, context):
    print(f"Event: {json.dumps(event)}")

    # API Gateway wraps the request body as a JSON string
    try:
        body = json.loads(event.get("body") or "{}")
        query = body.get("query", "").strip()
    except (json.JSONDecodeError, AttributeError):
        return {
            "statusCode": 400,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "Invalid JSON body"}),
        }

    if not query:
        return {
            "statusCode": 400,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "Missing required field: query"}),
        }

    print(f"Query: {query!r}")
    answer = invoke_supervisor(query)
    print(f"Answer: {answer!r}")

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({"answer": answer}),
    }
