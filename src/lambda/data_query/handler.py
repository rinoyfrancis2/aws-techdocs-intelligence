"""
Lambda: data_query
Triggered by Bedrock Agent Action Group (Data Agent)
Flow: parse query_type → run SQL against documents table → return metadata
"""
import os
import json
import psycopg2

RDS_HOST = os.environ["RDS_HOST"]
RDS_DB = os.environ["RDS_DB"]
RDS_USER = os.environ["RDS_USER"]
RDS_PASSWORD = os.environ["RDS_PASSWORD"]


def get_db():
    # Same pattern as rag_retriever — sslmode="require" is mandatory for RDS inside VPC
    return psycopg2.connect(
        host=RDS_HOST, dbname=RDS_DB, user=RDS_USER, password=RDS_PASSWORD,
        sslmode="require"
    )


def list_docs() -> dict:
    # Returns all indexed documents with their metadata
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT name, s3_key, chunk_count, status, ingested_at FROM documents ORDER BY ingested_at DESC"
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return {
        "documents": [
            {
                "name": row[0],
                "s3_key": row[1],
                "chunk_count": row[2],
                "status": row[3],
                "ingested_at": row[4].isoformat() if row[4] else None,
            }
            for row in rows
        ]
    }


def count_docs() -> dict:
    # Returns total number of indexed documents and total chunks
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*), COALESCE(SUM(chunk_count), 0) FROM documents")
    row = cur.fetchone()
    cur.close()
    conn.close()
    return {"doc_count": row[0], "total_chunks": int(row[1])}


def doc_status(doc_name: str) -> dict:
    # Returns status for a specific document — partial match on name
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT name, s3_key, chunk_count, status, ingested_at FROM documents WHERE name ILIKE %s",
        (f"%{doc_name}%",),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    if not rows:
        return {"error": f"No document found matching: {doc_name!r}"}
    return {
        "documents": [
            {
                "name": row[0],
                "s3_key": row[1],
                "chunk_count": row[2],
                "status": row[3],
                "ingested_at": row[4].isoformat() if row[4] else None,
            }
            for row in rows
        ]
    }


def parse_action_group_params(event: dict) -> dict:
    # functionSchema events send parameters as a flat list: [{name, type, value}, ...]
    return {p["name"]: p["value"] for p in event.get("parameters", [])}


def handler(event, context):
    print(f"Event: {json.dumps(event)}")

    action_group = event.get("actionGroup", "data-query")
    function_name = event.get("function", "query")

    params = parse_action_group_params(event)
    query_type = params.get("query_type", "").strip().lower()
    doc_name = params.get("doc_name", "").strip()

    print(f"query_type: {query_type!r}, doc_name: {doc_name!r}")

    if query_type == "list_docs":
        result = list_docs()
    elif query_type == "count_docs":
        result = count_docs()
    elif query_type == "doc_status":
        if not doc_name:
            result = {"error": "doc_status requires doc_name parameter"}
        else:
            result = doc_status(doc_name)
    else:
        result = {
            "error": f"Unknown query_type: {query_type!r}",
            "valid_types": ["list_docs", "count_docs", "doc_status"],
        }

    print(f"Result: {json.dumps(result)}")

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
