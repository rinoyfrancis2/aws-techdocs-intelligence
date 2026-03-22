"""
One-time Lambda to create pgvector schema in RDS.
Deploy inside the VPC, run once, then delete.
"""
import os
import json
import psycopg2

RDS_HOST = os.environ["RDS_HOST"]
RDS_DB = os.environ["RDS_DB"]
RDS_USER = os.environ["RDS_USER"]
RDS_PASSWORD = os.environ["RDS_PASSWORD"]


def handler(event, context):
    conn = psycopg2.connect(
        host=RDS_HOST, dbname=RDS_DB, user=RDS_USER, password=RDS_PASSWORD,
        sslmode="require"
    )
    conn.autocommit = True
    cur = conn.cursor()

    print("Enabling pgvector extension...")
    cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    print("Creating documents table...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name VARCHAR(500),
            s3_key VARCHAR(1000),
            source_type VARCHAR(50) DEFAULT 'pdf',
            ingested_at TIMESTAMP DEFAULT NOW(),
            chunk_count INTEGER DEFAULT 0,
            status VARCHAR(20) DEFAULT 'pending'
        );
    """)

    print("Creating document_chunks table...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS document_chunks (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            doc_id UUID REFERENCES documents(id) ON DELETE CASCADE,
            doc_name VARCHAR(500),
            chunk_index INTEGER,
            content TEXT,
            embedding vector(1024),
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)

    print("Creating vector index...")
    cur.execute("""
        CREATE INDEX IF NOT EXISTS chunks_embedding_idx
        ON document_chunks
        USING ivfflat (embedding vector_cosine_ops)
        WITH (lists = 100);
    """)

    print("Cleaning up partial documents...")
    cur.execute("DELETE FROM documents;")

    cur.close()
    conn.close()

    print("RDS schema setup complete.")
    return {"statusCode": 200, "body": "Schema created successfully"}
