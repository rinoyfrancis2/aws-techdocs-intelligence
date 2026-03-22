# AWS TechDocs Intelligence

A production-grade **multi-agent RAG system** built entirely on AWS — no managed vector stores, no third-party orchestration frameworks. Raw infrastructure, raw agents, raw control.

Ask a question via REST API. Four coordinated Bedrock Agents retrieve relevant document chunks, query metadata, and synthesise a final answer — all within a private VPC.

---

## Architecture

```
INGESTION PLANE
──────────────────────────────────────────────────────────────────────
 PDF Upload
    └─► S3 Bucket
           └─► document_processor Lambda  (ObjectCreated trigger)
                  ├── PyPDF2 text extraction
                  ├── LangChain chunking (500 chars, 50 overlap)
                  ├── Bedrock Titan Embeddings v2  (1024-dim)
                  └── INSERT → RDS PostgreSQL + pgvector

QUERY PLANE
──────────────────────────────────────────────────────────────────────
 User  POST /query  {"query": "..."}
    └─► API Gateway  (REGIONAL REST API)
           └─► api_gateway Lambda
                  └─► Supervisor Bedrock Agent
                         ├─► RAG Agent
                         │      └─► rag_retriever Lambda
                         │             └─► pgvector cosine search → top-k chunks
                         ├─► Data Agent
                         │      └─► data_query Lambda
                         │             └─► SQL metadata (list / count / status)
                         └─► Synthesis Agent  (pure LLM, no tools)
                                └─► Composes final answer
                                       └─► {"answer": "..."}  HTTP 200
```

![RAG Architecture Diagram](Rag%20diagram.excalidraw.png)

> Visual diagram: [`notes/architecture-overview.excalidraw`](notes/architecture-overview.excalidraw) — open at [excalidraw.com](https://excalidraw.com) or via VS Code Excalidraw extension.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Compute | AWS Lambda (Python 3.12) |
| AI Agents | AWS Bedrock Agents (multi-agent collaboration) |
| LLM | Claude Haiku 4.5 (inference profile, eu-west-1) |
| Embeddings | Amazon Titan Embeddings v2 (1024-dim) |
| Vector store | RDS PostgreSQL 15 + pgvector (ivfflat index) |
| Document store | S3 |
| API | API Gateway REST API (Lambda Proxy) |
| Networking | VPC + private subnets + VPC Endpoints (no NAT Gateway) |
| IaC | Python boto3 scripts (no CDK/Terraform) |
| PDF parsing | PyPDF2 |
| Chunking | LangChain RecursiveCharacterTextSplitter |

---

## Project Structure

```
aws-techdocs-intelligence/
├── .env.example                          ← copy to .env, fill in your values
├── requirements.txt
├── notes/
│   ├── architecture-overview.md          ← full component reference
│   └── architecture-overview.excalidraw  ← visual architecture diagram
├── prompts/
│   ├── supervisor_system_prompt.md
│   ├── rag_agent_system_prompt.md
│   ├── data_agent_system_prompt.md
│   └── synthesis_agent_system_prompt.md
├── src/
│   ├── infra/
│   │   ├── setup_rds.py                  ← creates pgvector schema (one-time)
│   │   ├── setup_s3.py                   ← creates S3 bucket (one-time)
│   │   ├── setup_bedrock_agents.py       ← creates all 4 agents + action groups
│   │   ├── setup_api_gateway.py          ← creates REST API + wires Lambda
│   │   └── rds_setup_lambda/
│   │       └── handler.py                ← VPC-internal DB management Lambda
│   ├── utils/
│   │   ├── bedrock_client.py
│   │   ├── rds_client.py
│   │   └── embeddings.py
│   └── lambda/
│       ├── document_processor/
│       │   └── handler.py                ← S3 trigger → PDF → chunks → RDS
│       ├── rag_retriever/
│       │   ├── handler.py                ← query → Titan embed → pgvector → top-k
│       │   ├── deploy.sh
│       │   └── test_local.py
│       ├── data_query/
│       │   ├── handler.py                ← list_docs / count_docs / doc_status
│       │   ├── deploy.sh
│       │   └── test_local.py
│       └── api_gateway/
│           ├── handler.py                ← parses POST body → invoke_agent
│           ├── deploy.sh
│           └── test_local.py             ← supports --live flag
```

---

## Prerequisites

- AWS account with Bedrock model access enabled (eu-west-1)
- AWS CLI configured (`aws configure`)
- Python 3.12
- Inference profile available: `eu.anthropic.claude-haiku-4-5-20251001-v1:0`

---

## Setup

### 1. Environment

```bash
cp .env.example .env
# Edit .env — fill in your AWS account ID, RDS creds, S3 bucket name
```

### 2. Infrastructure (one-time)

```bash
# Create S3 bucket and RDS schema
python src/infra/setup_s3.py
python src/infra/setup_rds.py

# Deploy all 4 Lambda functions
bash src/lambda/document_processor/deploy.sh
bash src/lambda/rag_retriever/deploy.sh
bash src/lambda/data_query/deploy.sh
bash src/lambda/api_gateway/deploy.sh

# Create Bedrock Agents (copy printed IDs into .env)
python src/infra/setup_bedrock_agents.py

# Wire API Gateway
python src/infra/setup_api_gateway.py
```

> **Before running deploy.sh:** replace `YOUR_ACCOUNT_ID`, `YOUR_SUBNET_ID_A/B`, and `YOUR_LAMBDA_SG_ID` in each deploy.sh with your own VPC values.

### 3. Ingest a document

```bash
aws s3 cp mydoc.pdf s3://YOUR_BUCKET_NAME/raw/mydoc.pdf
# document_processor Lambda triggers automatically via S3 ObjectCreated event
```

### 4. Query

```bash
# Direct Lambda invoke (no API Gateway needed)
python src/lambda/api_gateway/test_local.py

# Via live HTTP endpoint
python src/lambda/api_gateway/test_local.py --live

# Via curl
curl -X POST 'https://YOUR_API_ID.execute-api.eu-west-1.amazonaws.com/prod/query' \
  -H 'Content-Type: application/json' \
  -d '{"query": "What does this document say about X?"}'
```

---

## How the Multi-Agent System Works

The **Supervisor Agent** receives the query and delegates:

| Agent | Role | Tool |
|-------|------|------|
| Supervisor | Orchestrates all sub-agents | — |
| RAG Agent | Semantic search over document chunks | `rag_retriever` Lambda |
| Data Agent | Metadata queries (list docs, counts, status) | `data_query` Lambda |
| Synthesis Agent | Composes final answer from retrieved context | Pure LLM (no tools) |

Agents communicate via `agentCollaboration = SUPERVISOR` with `relayConversationHistory = TO_COLLABORATOR`. All action groups use `functionSchema` format (not OpenAPI).

---

## Key Engineering Decisions

**Private VPC with VPC Endpoints instead of NAT Gateway**
All Lambda → AWS service traffic (S3, Bedrock, RDS) stays within the VPC via Interface/Gateway endpoints. Saves ~$30/month vs NAT Gateway and keeps traffic off the internet.

**psycopg2 cross-compiled for Lambda**
`pip install psycopg2-binary --platform manylinux2014_x86_64` — required because Lambda runs on Linux (x86) but development is on macOS.

**Lambda env vars via `--cli-input-json` + Python JSON builder**
The AWS CLI `Variables={...}` shorthand breaks with special characters in passwords. Python-built JSON passed via `--cli-input-json` handles any character safely.

**Inference profiles in eu-west-1**
Classic model IDs (`anthropic.claude-haiku-*`) return `AccessDeniedException` in eu-west-1. The cross-region inference profile (`eu.anthropic.claude-haiku-4-5-20251001-v1:0`) is required.

**functionSchema action groups**
Bedrock Agent action groups use `event["function"]` and `functionResponse.responseBody.TEXT.body` — not the OpenAPI `apiPath`/`httpStatusCode` format. Mixing these causes `dependencyFailedException`.

---

## Cost (approximate, eu-west-1)

| Service | Cost |
|---------|------|
| Lambda | ~$0 (well within free tier) |
| RDS t3.micro | Free tier (750 hrs/month for 12 months) |
| S3 | ~$0 for small document sets |
| API Gateway | Free tier (1M calls/month for 12 months) |
| VPC Interface Endpoints (×3) | ~$10.50/month |
| Bedrock Titan Embeddings v2 | ~$0.02/1M tokens |
| Bedrock Claude Haiku 4.5 | ~$0.25/1M input tokens |

> To minimise cost during development: delete Interface Endpoints when not in use.

---

## N8N → AWS Mental Model

This project is the AWS equivalent of an N8N multi-agent workflow:

| N8N | AWS |
|-----|-----|
| Webhook trigger node | API Gateway → Lambda |
| S3 trigger node | S3 ObjectCreated → Lambda |
| AI Agent node | Bedrock Agent |
| Tool (in AI Agent) | Action Group → Lambda |
| Sub-workflow / sub-agent | Bedrock Agent collaborator |
| Embeddings node | Bedrock Titan Embeddings v2 |
| Postgres node | psycopg2 → RDS |
| Vector store node | pgvector (`<=>` cosine operator) |

---

## Author

Built by **Rinoy Francis** — AI Automation Engineer
[LinkedIn](https://linkedin.com/in/rinoyfrancis) · [GitHub](https://github.com/rinoyfrancis)
