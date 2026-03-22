"""
Lambda: rag_retriever
Triggered by Bedrock Agent Action Group (RAG Agent)
Flow: query → Titan embedding → pgvector cosine search → return top-k chunks
"""
import os
import json
import boto3
import psycopg2

REGION = os.environ.get("AWS_REGION", "eu-west-1")
RDS_HOST = os.environ["RDS_HOST"]
RDS_DB = os.environ["RDS_DB"]
RDS_USER = os.environ["RDS_USER"]
RDS_PASSWORD = os.environ["RDS_PASSWORD"]
TITAN_MODEL_ID = "amazon.titan-embed-text-v2:0"

# Initialised outside the handler so it's reused across warm Lambda invocations
# (avoids re-creating the boto3 client on every call)
bedrock = boto3.client("bedrock-runtime", region_name=REGION)


def get_db():
    # New connection per invocation — Lambda doesn't persist state between cold starts,
    # and connection pooling (e.g. RDS Proxy) is overkill for this project volume.
    # sslmode="require" is mandatory — RDS rejects plaintext connections inside the VPC.
    return psycopg2.connect(
        host=RDS_HOST, dbname=RDS_DB, user=RDS_USER, password=RDS_PASSWORD,
        sslmode="require"
    )


def get_embedding(text: str) -> list:
    # Titan Embeddings v2 produces 1024-dim vectors — must match what document_processor used.
    # If the model ever changes, all stored embeddings become incompatible (re-index required).
    body = json.dumps({"inputText": text})
    response = bedrock.invoke_model(
        modelId=TITAN_MODEL_ID,
        body=body,
        contentType="application/json",
        accept="application/json",
    )
    return json.loads(response["body"].read())["embedding"]


def retrieve(query: str, top_k: int = 5) -> list:
    embedding = get_embedding(query)
    # pgvector expects the vector as a string literal e.g. "[0.1, 0.2, ...]"
    embedding_str = str(embedding)

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT content, doc_name, chunk_index,
               1 - (embedding <=> %s::vector) AS score
        FROM document_chunks
        ORDER BY embedding <=> %s::vector
        LIMIT %s
        """,
        (embedding_str, embedding_str, top_k),
        # <=> is pgvector cosine DISTANCE (0 = identical, 2 = opposite).
        # We ORDER BY distance ascending (most similar first),
        # and return score = 1 - distance so higher score = better match.
        # The embedding appears twice: once for ORDER BY, once for the score column.
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    return [
        {"content": row[0], "doc_name": row[1], "chunk_index": row[2], "score": round(float(row[3]), 4)}
        for row in rows
    ]


def parse_action_group_params(event: dict) -> dict:
    # functionSchema events send parameters as a flat list: [{name, type, value}, ...]
    # Much simpler than the OpenAPI requestBody nesting.
    return {p["name"]: p["value"] for p in event.get("parameters", [])}


def handler(event, context):
    print(f"Event: {json.dumps(event)}")

    action_group = event.get("actionGroup", "rag-search")
    function_name = event.get("function", "retrieve")

    params = parse_action_group_params(event)
    query = params.get("query", "").strip()
    top_k = int(params.get("top_k", 5))

    if not query:
        result = {"error": "Missing required parameter: query"}
    else:
        print(f"Query: {query!r}, top_k: {top_k}")
        results = retrieve(query, top_k)
        print(f"Retrieved {len(results)} chunks")
        result = {"results": results}

    # functionSchema response format — body must be a plain string
    return {
        "messageVersion": "1.0",
        "response": {
            "actionGroup": action_group,
            "function": function_name,
            "functionResponse": {
                "responseBody": {
                    "TEXT": {
                        "body": json.dumps(result)
                    }
                }
            },
        },
    }
