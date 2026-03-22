"""
Run this script once to create the pgvector schema in RDS.
Usage: python -m src.infra.setup_rds
"""
from src.utils.rds_client import get_connection


def setup():
    conn = get_connection()
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

    cur.close()
    conn.close()
    print("RDS schema setup complete.")


if __name__ == "__main__":
    setup()
