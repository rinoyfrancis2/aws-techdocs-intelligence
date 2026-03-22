# AWS TechDocs Intelligence System — Full Architecture & Configuration

## Project Goal
A multi-agent RAG pipeline that:
1. Ingests PDF documents into S3
2. Processes and chunks them via Lambda
3. Stores embeddings in RDS PostgreSQL (pgvector)
4. Answers questions via 4 coordinated Bedrock Agents exposed through API Gateway

---

## Architecture Diagram

```
QUERY PLANE:

[User]
  │ POST /query  {"query": "..."}
  ▼
[API Gateway]  ← techdocs-api, stage: prod, REGIONAL endpoint
  │
  ▼
[Lambda: api_gateway]  ← Lambda Proxy integration
  │  parse body → create session_id → invoke_agent(supervisor)
  ▼
[Bedrock: Supervisor Agent]  ← APRAWFMJEN / alias JGFHVWYTM2
  │  Claude Haiku 4.5 (eu.anthropic.claude-haiku-4-5-20251001-v1:0)
  │  agentCollaboration = SUPERVISOR
  │  relayConversationHistory = TO_COLLABORATOR
  │
  ├──────────────────────────────────────────────────────────────┐
  │                                                              │
  ▼                                                              ▼
[RAG Agent]  ← IX3TIZQTXU / alias XGK0X935GI           [Data Agent]  ← YQAGKX5CKU / alias ULRGV5UC2L
  │  action group: rag-search                              │  action group: data-query
  ▼                                                        ▼
[Lambda: rag_retriever]                           [Lambda: data_query]
  │  embed query (Titan v2, 1024-dim)               │  SQL on documents table
  │  pgvector cosine search (<=> operator)          │  list_docs / count_docs / doc_status
  ▼                                                 ▼
[RDS PostgreSQL + pgvector]  ←────────────────────┘
  tables: documents, document_chunks
  endpoint: techdocs-db.chwm4ccy2b7c.eu-west-1.rds.amazonaws.com:5432
  │
  ▲
  └─── results fed back to Supervisor ──► [Synthesis Agent] ← WQCNRO3SHR / alias DFTM5OSCO3
                                            no action group — pure LLM
                                            composes final answer
                                            │
                                            ▼
                                    Final answer streamed back
                                    through Supervisor → api_gateway Lambda
                                    → API Gateway → HTTP 200 {"answer": "..."}

INGESTION PLANE:

[S3: techdocs-raw-rinoy]
  │  upload: aws s3 cp myfile.pdf s3://techdocs-raw-rinoy/raw/myfile.pdf
  │  S3 ObjectCreated event on prefix raw/
  ▼
[Lambda: document_processor]
  ├── Download PDF from S3 (via VPC Gateway endpoint)
  ├── Extract text — PyPDF2
  ├── Chunk text — LangChain RecursiveCharacterTextSplitter (500 chars, 50 overlap)
  ├── Embed each chunk — Bedrock Titan Embeddings v2 (1024-dim)
  └── INSERT → documents table (status: indexed) + document_chunks table (embedding vector)
```

---

## AWS Infrastructure Configuration

### Region
- **eu-west-1 (Ireland)**

### Account ID
- **940307564102**

---

## VPC Configuration

| Resource | Name | Value |
|----------|------|-------|
| VPC | techdocs-vpc | CIDR: 10.0.0.0/16 |
| DNS Hostnames | enabled | Required for VPC Endpoints |
| DNS Resolution | enabled | Required for VPC Endpoints |
| Subnet A | techdocs-private-a | 10.0.1.0/24, eu-west-1a, ID: subnet-092f601b7c8c9301b |
| Subnet B | techdocs-private-b | 10.0.2.0/24, eu-west-1b, ID: subnet-0e7e005bf1b2be39e |

### Security Groups

| Name | ID | Inbound | Outbound |
|------|----|---------|----------|
| techdocs-lambda-sg | sg-0b11c4060782fcc7c | none | ALL to 0.0.0.0/0 |
| techdocs-rds-sg | (check console) | port 5432 from lambda-sg | none |
| techdocs-endpoint-sg | (check console) | port 443 from lambda-sg | ALL |

### VPC Endpoints

| Endpoint | Type | Service | Why |
|----------|------|---------|-----|
| techdocs-s3-endpoint | Gateway (FREE) | com.amazonaws.eu-west-1.s3 | Lambda → S3 without internet |
| techdocs-bedrock-runtime-endpoint | Interface | com.amazonaws.eu-west-1.bedrock-runtime | Lambda → Titan Embeddings |
| techdocs-bedrock-agent-runtime-endpoint | Interface | com.amazonaws.eu-west-1.bedrock-agent-runtime | api_gateway Lambda → invoke_agent |
| techdocs-logs-endpoint | Interface | com.amazonaws.eu-west-1.logs | Lambda → CloudWatch Logs |

**S3 Gateway endpoint gotcha:** Must run `modify-vpc-endpoint --add-route-table-ids` after creation — otherwise Lambda silently hangs on S3 download.

**Why VPC Endpoints instead of NAT Gateway:**
- NAT Gateway costs ~$30/month
- VPC Endpoints cost ~$0.01/hr per interface endpoint
- Keeps all traffic private — no internet exposure

---

## RDS Configuration

| Setting | Value |
|---------|-------|
| Instance ID | techdocs-db |
| Engine | PostgreSQL 15 |
| Instance type | db.t3.micro (free tier) |
| Storage | 20GB GP2 |
| VPC | techdocs-vpc |
| Subnet Group | techdocs-db-subnet-group |
| Security Group | techdocs-rds-sg |
| Public Access | NO (private VPC only) |
| AZ | eu-west-1a |
| Endpoint | techdocs-db.chwm4ccy2b7c.eu-west-1.rds.amazonaws.com |
| Port | 5432 |
| Master username | postgres |
| SSL | required (sslmode="require" in psycopg2.connect) |

**Note:** RDS has no public access. To query it directly, invoke the `techdocs-rds-setup` Lambda which runs inside the VPC.

### Database Schema

```sql
-- Extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Documents table (PDF metadata)
CREATE TABLE documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(500),
    s3_key VARCHAR(1000),
    source_type VARCHAR(50) DEFAULT 'pdf',
    ingested_at TIMESTAMP DEFAULT NOW(),
    chunk_count INTEGER DEFAULT 0,
    status VARCHAR(20) DEFAULT 'pending'  -- 'pending', 'indexing', 'indexed'
);

-- Chunks table (text + embeddings)
CREATE TABLE document_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id UUID REFERENCES documents(id) ON DELETE CASCADE,
    doc_name VARCHAR(500),
    chunk_index INTEGER,
    content TEXT,
    embedding vector(1024),   -- Titan Embeddings v2 = 1024 dimensions
    created_at TIMESTAMP DEFAULT NOW()
);

-- Vector similarity search index
CREATE INDEX chunks_embedding_idx ON document_chunks
USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
```

---

## S3 Configuration

| Setting | Value |
|---------|-------|
| Bucket name | techdocs-raw-rinoy |
| Region | eu-west-1 |
| Type | General Purpose |
| Public access | Blocked |
| Versioning | Enabled |
| Upload prefix | raw/ |

**How to upload a doc:**
```bash
aws s3 cp myfile.pdf s3://techdocs-raw-rinoy/raw/myfile.pdf
```
S3 triggers `document_processor` Lambda automatically on upload.

---

## IAM Roles

| Role | Policies | Used By |
|------|----------|---------|
| techdocs-lambda-role | BedrockFullAccess, S3, RDS, CloudWatch, AWSLambdaVPCAccessExecutionRole | All Lambda functions |
| techdocs-bedrock-agent-role | BedrockFullAccess, LambdaRole | Bedrock Agents |

---

## Lambda Functions

### document_processor
- **ARN**: `arn:aws:lambda:eu-west-1:940307564102:function:document_processor`
- **Trigger**: S3 ObjectCreated event on bucket `techdocs-raw-rinoy`, prefix `raw/`
- **Purpose**: Ingestion pipeline — turns a PDF into searchable vector chunks
- **Flow**: Download PDF → PyPDF2 extract → LangChain chunk (500 chars, 50 overlap) → Titan embed each chunk → INSERT into `documents` + `document_chunks`
- **Runtime**: Python 3.12, 256MB, 300s timeout
- **VPC**: techdocs-private-a, techdocs-private-b / sg-0b11c4060782fcc7c
- **Status**: ✅ Deployed and tested (nmap-cheatsheet.pdf → 14 chunks)

### rag_retriever
- **ARN**: `arn:aws:lambda:eu-west-1:940307564102:function:rag_retriever`
- **Trigger**: Bedrock Agent Action Group — called by RAG Agent (`rag-search` / `retrieve`)
- **Purpose**: Semantic search — finds the most relevant document chunks for a query
- **Flow**: Embed query (Titan Embeddings v2) → cosine similarity search (`<=>`) → return top-k chunks with scores
- **Input**: `query` (string), `top_k` (int, default 5)
- **Output**: `{"results": [{"content": "...", "doc_name": "...", "chunk_index": N, "score": 0.xxx}]}`
- **Score meaning**: 1.0 = perfect match, 0.0 = no match (cosine similarity)
- **Response format**: Bedrock functionSchema — `functionResponse.responseBody.TEXT.body`
- **Runtime**: Python 3.12, 256MB, 60s timeout
- **VPC**: techdocs-private-a, techdocs-private-b / sg-0b11c4060782fcc7c
- **Status**: ✅ Deployed and tested (nmap query score 0.459)

### data_query
- **ARN**: `arn:aws:lambda:eu-west-1:940307564102:function:data_query`
- **Trigger**: Bedrock Agent Action Group — called by Data Agent (`data-query` / `query`)
- **Purpose**: Metadata queries about what documents exist, counts, dates
- **Supported query_types**:
  - `list_docs` → all docs with chunk counts + status
  - `count_docs` → total doc count + total chunks
  - `doc_status` → status for a specific doc (partial name match)
- **Output**: Structured metadata from `documents` table
- **Response format**: Bedrock functionSchema — `functionResponse.responseBody.TEXT.body`
- **Runtime**: Python 3.12, 256MB, 60s timeout
- **VPC**: techdocs-private-a, techdocs-private-b / sg-0b11c4060782fcc7c
- **Status**: ✅ Deployed and tested (count=1 doc / 14 chunks verified)

### api_gateway
- **ARN**: `arn:aws:lambda:eu-west-1:940307564102:function:api_gateway`
- **Trigger**: API Gateway POST /query (Lambda Proxy integration)
- **Purpose**: Entry point — receives HTTP request, invokes Supervisor Agent, returns final answer
- **Flow**: Parse JSON body → extract `query` → generate `session_id` (uuid4) → `invoke_agent(supervisor)` → stream EventStream → return `{"answer": "..."}`
- **Input event shape** (from API Gateway):
  ```json
  { "body": "{\"query\": \"What does nmap say about SYN scans?\"}" }
  ```
- **Output**: `{"statusCode": 200, "body": "{\"answer\": \"...\"}"}` or 400 on bad input
- **Env vars**: `SUPERVISOR_AGENT_ID=APRAWFMJEN`, `SUPERVISOR_AGENT_ALIAS_ID=JGFHVWYTM2`
- **Runtime**: Python 3.12, 256MB, 120s timeout
- **VPC**: techdocs-private-a, techdocs-private-b / sg-0b11c4060782fcc7c
- **Status**: ✅ Deployed and tested via `test_local.py` (full agent chain working)

### techdocs-rds-setup
- **Trigger**: Manual (one-time / maintenance use only)
- **Purpose**: Runs inside VPC to manage RDS — creates pgvector extension, tables, index. Also used to wipe data (`DELETE FROM documents`)
- **Status**: ✅ Deployed (schema created, used for cleanup)

---

## API Gateway

| Setting | Value |
|---------|-------|
| API Name | techdocs-api |
| Type | REST API |
| Endpoint type | REGIONAL |
| Resource | /query |
| Method | POST |
| Auth | NONE |
| Integration type | AWS_PROXY (Lambda Proxy) |
| Lambda function | api_gateway |
| Stage | prod |
| Invoke URL | https://{api-id}.execute-api.eu-west-1.amazonaws.com/prod/query |

**Why Lambda Proxy integration:**
API Gateway passes the full HTTP request as-is to Lambda (headers, body, method, path). Lambda returns the full HTTP response (statusCode, headers, body). The `api_gateway` handler is already written for this exact format.

**How to create (automated):**
```bash
python src/infra/setup_api_gateway.py
```
Creates REST API, /query resource, POST method, Lambda permission, and deploys to prod stage. Saves invoke URL to `outputs/api_gateway_config.json`.

**Test after wiring:**
```bash
# Mode 1 — direct Lambda (no API Gateway needed)
python src/lambda/api_gateway/test_local.py

# Mode 2 — live HTTP via API Gateway
python src/lambda/api_gateway/test_local.py --live

# Mode 3 — curl
curl -X POST 'https://{api-id}.execute-api.eu-west-1.amazonaws.com/prod/query' \
  -H 'Content-Type: application/json' \
  -d '{"query": "What does the nmap cheatsheet say about SYN scans?"}'
```

**Lambda invoke permission (added by setup script):**
```bash
aws lambda add-permission \
  --function-name api_gateway \
  --statement-id apigateway-techdocs-invoke \
  --action lambda:InvokeFunction \
  --principal apigateway.amazonaws.com \
  --source-arn "arn:aws:execute-api:eu-west-1:940307564102:{api-id}/*/POST/query"
```

---

## Bedrock Models

| Model | Model ID | Purpose |
|-------|----------|---------|
| Titan Embeddings V2 | amazon.titan-embed-text-v2:0 | 1024-dim text embeddings |
| Claude Haiku 4.5 | eu.anthropic.claude-haiku-4-5-20251001-v1:0 | LLM for all 4 agents |

**Important:** In eu-west-1, use the inference profile ID (`eu.anthropic...`) not the base model ID (`anthropic.claude...`). The base ID will return `AccessDeniedException`. The "Model access" console page is retired — inference profiles are the replacement.

---

## Bedrock Agents

| Agent | Agent ID | Alias ID | Role |
|-------|----------|----------|------|
| Supervisor | APRAWFMJEN | JGFHVWYTM2 | Orchestrates all sub-agents. Entry point from api_gateway Lambda. |
| RAG Agent | IX3TIZQTXU | XGK0X935GI | Calls rag_retriever Lambda via action group `rag-search` / function `retrieve` |
| Data Agent | YQAGKX5CKU | ULRGV5UC2L | Calls data_query Lambda via action group `data-query` / function `query` |
| Synthesis Agent | WQCNRO3SHR | DFTM5OSCO3 | No action group — pure LLM, writes the final answer |

**Collaboration settings:**
- `agentCollaboration = SUPERVISOR` (set on Supervisor agent)
- `relayConversationHistory = TO_COLLABORATOR` (set on each collaborator association)

**Agent collaborator flow:**
```
api_gateway Lambda
  └─► Supervisor (APRAWFMJEN)
        ├─► RAG Agent (IX3TIZQTXU)
        │     └─► rag_retriever Lambda → pgvector → top-k chunks
        ├─► Data Agent (YQAGKX5CKU)
        │     └─► data_query Lambda → documents table → metadata
        └─► Synthesis Agent (WQCNRO3SHR)
              └─► Pure LLM — combines RAG + metadata → final answer
```

**Only two IDs needed in `.env`:**
```
SUPERVISOR_AGENT_ID=APRAWFMJEN
SUPERVISOR_AGENT_ALIAS_ID=JGFHVWYTM2
```

---

## Action Group Event Format (functionSchema)

Both rag_retriever and data_query use `functionSchema` action groups (not OpenAPI schema). The Lambda event and response shapes differ:

**Incoming event from Bedrock Agent:**
```python
event = {
    "function": "retrieve",        # or "query"
    "parameters": [
        {"name": "query", "value": "What is nmap?"},
        {"name": "top_k", "value": "5"}
    ]
}
```

**Required response format:**
```python
return {
    "messageVersion": "1.0",
    "response": {
        "actionGroup": "rag-search",
        "function": "retrieve",
        "functionResponse": {
            "responseBody": {
                "TEXT": {
                    "body": json.dumps({"results": [...]})
                }
            }
        }
    }
}
```
**Common mistake:** Writing the handler for OpenAPI format (`apiPath`, `httpStatusCode`, `responseBody` at top level). That causes `dependencyFailedException` in the Bedrock Agent runtime.

---

## N8N → AWS Mental Model

| N8N Concept | AWS Equivalent | Notes |
|-------------|----------------|-------|
| Workflow | Lambda function | One Lambda = one unit of work |
| Webhook trigger node | API Gateway → Lambda | API Gateway is the "door in" |
| S3 node trigger | S3 Event → Lambda | Same concept, native AWS |
| AI Agent node | Bedrock Agent | Agent + system prompt + tools |
| Tool (in AI Agent) | Action Group → Lambda | Each tool = one Lambda + functionSchema |
| Sub-workflow / sub-agent | Bedrock Agent collaborator | Supervisor invokes sub-agents |
| Embeddings node | bedrock-runtime → Titan Embeddings v2 | 1024-dim output |
| Postgres node | psycopg2 → RDS | Same SQL, just manual connection |
| Vector store node | pgvector in RDS | `<=>` cosine operator |
| CloudWatch Logs | N8N execution log | `print()` in Lambda → Logs |
| Environment variables | Lambda env vars (set via console or deploy.sh) | Same concept |
| Credentials | IAM role attached to Lambda | No manual key management needed |

---

## Cost Breakdown

| Service | Free Tier | After Free Tier | This Project |
|---------|-----------|-----------------|--------------|
| S3 | 5GB/month (12 months) | ~$0.01/month | ~$0 |
| Lambda | 1M req/month (forever) | $0 forever | $0 |
| RDS t3.micro | 750 hrs/month (12 months) | ~$15/month | Free tier active |
| API Gateway | 1M calls/month (12 months) | negligible | Free tier active |
| VPC Interface Endpoints | not free | ~$3.50/month each | ~$10.50/month (3 interface) |
| Bedrock Claude Haiku 4.5 | no free tier | ~$0.25/1M input tokens | Pennies for testing |
| Bedrock Titan Embeddings v2 | no free tier | $0.02/1M tokens | ~$0.01 for this project |

**When done learning:** Delete VPC Interface Endpoints = saves ~$10.50/month. RDS free tier covers 750 hrs = 31 days/month = always on.

---

## Lessons Learned / Gotchas

| Issue | Cause | Fix |
|-------|-------|-----|
| psycopg2 import error in Lambda | Mac-compiled binary doesn't run on Linux (Lambda) | `pip install psycopg2-binary --platform manylinux2014_x86_64 --only-binary=:all:` |
| RDS password auth failed | Special characters in password broke CLI `Variables={...}` shorthand | Use simple alphanumeric password (e.g. `Techdocs2024`). Or use `--cli-input-json` with Python-built JSON |
| Lambda stays in Pending state | VPC Lambda takes 60-90s to create ENIs | Add `aws lambda wait function-active` before `update-function-configuration` |
| Cannot connect to RDS from local Mac | VPC has no internet gateway, RDS is private-only | Use `techdocs-rds-setup` Lambda inside VPC for any direct DB access |
| Lambda hangs on S3 download | S3 VPC Gateway endpoint created but route table not associated | `aws ec2 modify-vpc-endpoint --add-route-table-ids <rtb-id>` |
| RDS connection hangs silently | psycopg2.connect() missing `sslmode="require"` | Always include `sslmode="require"` in RDS connection string |
| `update-function-configuration` fails on new Lambda | Lambda still in Pending state | Add `aws lambda wait function-active` before updating config |
| Large PDFs timeout Lambda (1473 chunks) | Titan embedding each chunk is slow; 900s limit hit | Keep test docs small (< 50 chunks). Large docs need async/chunked processing |
| Duplicate docs in RDS | Re-uploading same S3 key re-triggers document_processor | Wipe with `techdocs-rds-setup` Lambda then re-upload once cleanly |
| `dependencyFailedException` in Bedrock Agent | Lambda handler written for OpenAPI format but action group uses functionSchema | Use `event["function"]` and `functionResponse.responseBody.TEXT.body` format |
| `AccessDeniedException` on Claude model | Base model ID not available in eu-west-1 via legacy Model Access | Use inference profile: `eu.anthropic.claude-haiku-4-5-20251001-v1:0` |
| `Variables={...}` CLI shorthand breaks with password | Shell treats `!` or `@` as special characters | Use `--cli-input-json` with JSON built via Python subprocess |

---

## Completed Steps

- [x] IAM roles created (techdocs-lambda-role, techdocs-bedrock-agent-role)
- [x] VPC created (techdocs-vpc, 10.0.0.0/16)
- [x] 2 private subnets created (techdocs-private-a / b)
- [x] 3 security groups created (lambda-sg, rds-sg, endpoint-sg)
- [x] 4 VPC endpoints created (S3 gateway + bedrock-runtime, bedrock-agent-runtime, logs interface)
- [x] S3 VPC Gateway endpoint route table associated (fix for Lambda S3 hang)
- [x] RDS subnet group created
- [x] RDS PostgreSQL deployed (techdocs-db, PostgreSQL 15, db.t3.micro)
- [x] S3 bucket created (techdocs-raw-rinoy)
- [x] pgvector schema created (documents + document_chunks + ivfflat index)
- [x] document_processor Lambda deployed + S3 trigger wired + tested ✅
- [x] rag_retriever Lambda deployed + tested ✅ (nmap-cheatsheet.pdf, score 0.459)
- [x] data_query Lambda deployed + tested ✅ (1 doc / 14 chunks, all query types verified)
- [x] 4 Bedrock Agents created, aliased, action groups wired, multi-agent collaboration configured ✅
  - Supervisor:  APRAWFMJEN / alias JGFHVWYTM2
  - RAG:         IX3TIZQTXU / alias XGK0X935GI
  - Data:        YQAGKX5CKU / alias ULRGV5UC2L
  - Synthesis:   WQCNRO3SHR / alias DFTM5OSCO3
- [x] api_gateway Lambda deployed + tested via test_local.py ✅ (full agent chain working)
- [x] setup_api_gateway.py written (automates REST API creation + Lambda wiring)
- [ ] Run `python src/infra/setup_api_gateway.py` to create live REST API
- [ ] End-to-end test via public URL (`test_local.py --live`)

---

## Project Folder Structure

```
aws-techdocs-intelligence/
├── .env                              ← RDS creds + Supervisor Agent IDs (never commit)
├── .env.example                      ← template
├── requirements.txt                  ← boto3, psycopg2-binary, PyPDF2, langchain, python-dotenv
├── notes/
│   └── architecture-overview.md     ← this file — single source of truth
├── prompts/                          ← system prompts for all 4 Bedrock Agents
│   ├── supervisor_system_prompt.md   ✅
│   ├── rag_agent_system_prompt.md    ✅
│   ├── data_agent_system_prompt.md   ✅
│   └── synthesis_agent_system_prompt.md ✅
├── outputs/
│   └── api_gateway_config.json       ← written by setup_api_gateway.py (invoke URL + api_id)
├── src/
│   ├── infra/
│   │   ├── setup_rds.py              ✅ one-time RDS schema setup
│   │   ├── setup_s3.py               ✅ one-time S3 bucket setup
│   │   ├── setup_bedrock_agents.py   ✅ creates all 4 agents + aliases + action groups
│   │   ├── setup_api_gateway.py      ✅ creates REST API + wires api_gateway Lambda
│   │   └── rds_setup_lambda/
│   │       └── handler.py            ✅ deployed as techdocs-rds-setup Lambda (VPC-internal)
│   ├── utils/
│   │   ├── bedrock_client.py         ← boto3 Bedrock client factory
│   │   ├── rds_client.py             ← psycopg2 RDS connection factory
│   │   └── embeddings.py             ← Titan Embeddings v2 wrapper
│   └── lambda/
│       ├── document_processor/
│       │   ├── handler.py            ✅ deployed — S3 trigger → PDF → chunks → RDS
│       │   └── deploy.sh             ✅
│       ├── rag_retriever/
│       │   ├── handler.py            ✅ deployed — query → Titan embed → pgvector → top-k chunks
│       │   ├── deploy.sh             ✅
│       │   └── test_local.py         ✅ tested (nmap score 0.459)
│       ├── data_query/
│       │   ├── handler.py            ✅ deployed — list_docs / count_docs / doc_status
│       │   ├── deploy.sh             ✅
│       │   └── test_local.py         ✅ tested (1 doc / 14 chunks)
│       └── api_gateway/
│           ├── handler.py            ✅ deployed — parses POST body → invoke_agent(supervisor)
│           ├── deploy.sh             ✅
│           └── test_local.py         ✅ supports --live flag (reads URL from outputs/api_gateway_config.json)
```

---

## Quick Reference — Run Order (First Time Setup)

```bash
# 1. Infrastructure (one-time)
python src/infra/setup_rds.py
python src/infra/setup_s3.py
# (deploy all Lambdas via their deploy.sh)
python src/infra/setup_bedrock_agents.py
python src/infra/setup_api_gateway.py   # ← creates live HTTP endpoint

# 2. Ingest a document
aws s3 cp myfile.pdf s3://techdocs-raw-rinoy/raw/myfile.pdf

# 3. Test (direct Lambda — no API Gateway needed)
python src/lambda/rag_retriever/test_local.py
python src/lambda/data_query/test_local.py
python src/lambda/api_gateway/test_local.py

# 4. Test (live HTTP endpoint)
python src/lambda/api_gateway/test_local.py --live
```
