"""
Lambda: document_processor
Triggered by S3 ObjectCreated event on prefix raw/
Flow: S3 download → PDF extract → chunk → embed → store in RDS
"""
import os
import json
import boto3
import PyPDF2
import psycopg2
from io import BytesIO
from langchain_text_splitters import RecursiveCharacterTextSplitter

REGION = os.environ.get("AWS_REGION", "eu-west-1")
RDS_HOST = os.environ["RDS_HOST"]
RDS_DB = os.environ["RDS_DB"]
RDS_USER = os.environ["RDS_USER"]
RDS_PASSWORD = os.environ["RDS_PASSWORD"]
TITAN_MODEL_ID = "amazon.titan-embed-text-v2:0"

s3 = boto3.client("s3", region_name=REGION)
bedrock = boto3.client("bedrock-runtime", region_name=REGION)


def get_db():
    return psycopg2.connect(
        host=RDS_HOST, dbname=RDS_DB, user=RDS_USER, password=RDS_PASSWORD,
        sslmode="require"
    )


def get_embedding(text: str) -> list:
    body = json.dumps({"inputText": text})
    response = bedrock.invoke_model(
        modelId=TITAN_MODEL_ID,
        body=body,
        contentType="application/json",
        accept="application/json",
    )
    return json.loads(response["body"].read())["embedding"]


def extract_text(pdf_bytes: bytes) -> str:
    reader = PyPDF2.PdfReader(BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def handler(event, context):
    for record in event["Records"]:
        bucket = record["s3"]["bucket"]["name"]
        s3_key = record["s3"]["object"]["key"]
        doc_name = s3_key.split("/")[-1]

        print(f"Processing: {s3_key}")

        # Download PDF
        obj = s3.get_object(Bucket=bucket, Key=s3_key)
        pdf_bytes = obj["Body"].read()

        # Extract text
        text = extract_text(pdf_bytes)
        if not text.strip():
            print(f"No text extracted from {doc_name}, skipping.")
            return

        # Chunk text
        splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
        chunks = splitter.split_text(text)
        print(f"Split into {len(chunks)} chunks")

        conn = get_db()
        cur = conn.cursor()

        # Insert document record
        cur.execute(
            """
            INSERT INTO documents (name, s3_key, chunk_count, status)
            VALUES (%s, %s, %s, 'indexing')
            RETURNING id
            """,
            (doc_name, s3_key, len(chunks)),
        )
        doc_id = cur.fetchone()[0]
        conn.commit()

        # Embed and insert each chunk
        for i, chunk in enumerate(chunks):
            embedding = get_embedding(chunk)
            cur.execute(
                """
                INSERT INTO document_chunks (doc_id, doc_name, chunk_index, content, embedding)
                VALUES (%s, %s, %s, %s, %s::vector)
                """,
                (doc_id, doc_name, i, chunk, str(embedding)),
            )

        # Mark document as indexed
        cur.execute(
            "UPDATE documents SET status = 'indexed' WHERE id = %s", (doc_id,)
        )
        conn.commit()
        cur.close()
        conn.close()

        print(f"Done: {doc_name} — {len(chunks)} chunks indexed")

    return {"statusCode": 200, "body": "OK"}
