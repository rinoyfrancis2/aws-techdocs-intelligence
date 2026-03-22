"""
setup_bedrock_agents.py
Creates all 4 Bedrock Agents, wires action groups to Lambdas, sets up multi-agent collaboration.

Run from project root:
    python src/infra/setup_bedrock_agents.py

Creation order (required):
    RAG Agent → Data Agent → Synthesis Agent → Supervisor (references all three)

After running, copy the printed IDs into your .env file.
"""
import boto3
import json
import os
import time
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
REGION = os.environ.get("AWS_REGION", "eu-west-1")
ACCOUNT_ID = os.environ.get("AWS_ACCOUNT_ID", "YOUR_ACCOUNT_ID")  # set in .env
AGENT_ROLE_ARN = f"arn:aws:iam::{ACCOUNT_ID}:role/techdocs-bedrock-agent-role"
MODEL_ID = "eu.anthropic.claude-haiku-4-5-20251001-v1:0"

LAMBDA_ARN = {
    "rag_retriever": f"arn:aws:lambda:{REGION}:{ACCOUNT_ID}:function:rag_retriever",
    "data_query":    f"arn:aws:lambda:{REGION}:{ACCOUNT_ID}:function:data_query",
}

PROMPTS_DIR = Path("prompts")

# ── Clients ───────────────────────────────────────────────────────────────────
bedrock = boto3.client("bedrock-agent", region_name=REGION)
lambda_client = boto3.client("lambda", region_name=REGION)


# ── Helpers ───────────────────────────────────────────────────────────────────

def read_prompt(filename: str) -> str:
    return (PROMPTS_DIR / filename).read_text().strip()


def wait_for_agent(agent_id: str, target_status: str = "NOT_PREPARED"):
    """Poll until agent reaches target status."""
    for _ in range(30):
        resp = bedrock.get_agent(agentId=agent_id)
        status = resp["agent"]["agentStatus"]
        print(f"  Agent {agent_id} status: {status}")
        if status == target_status:
            return
        if status in ("FAILED", "DELETING"):
            raise RuntimeError(f"Agent {agent_id} entered unexpected status: {status}")
        time.sleep(5)
    raise TimeoutError(f"Agent {agent_id} did not reach {target_status} in time")


def prepare_and_alias(agent_id: str, alias_name: str) -> tuple[str, str]:
    """Prepare agent and create an alias. Returns (alias_id, alias_arn)."""
    print(f"  Preparing agent {agent_id}...")
    bedrock.prepare_agent(agentId=agent_id)

    # Wait for PREPARED status
    for _ in range(30):
        resp = bedrock.get_agent(agentId=agent_id)
        status = resp["agent"]["agentStatus"]
        print(f"  Status: {status}")
        if status == "PREPARED":
            break
        if status == "FAILED":
            raise RuntimeError(f"Agent {agent_id} failed to prepare")
        time.sleep(5)
    else:
        raise TimeoutError(f"Agent {agent_id} did not reach PREPARED")

    print(f"  Creating alias '{alias_name}'...")
    alias_resp = bedrock.create_agent_alias(
        agentId=agent_id,
        agentAliasName=alias_name,
    )
    alias_id = alias_resp["agentAlias"]["agentAliasId"]

    # Wait for alias to be PREPARED
    for _ in range(30):
        resp = bedrock.get_agent_alias(agentId=agent_id, agentAliasId=alias_id)
        status = resp["agentAlias"]["agentAliasStatus"]
        print(f"  Alias status: {status}")
        if status == "PREPARED":
            break
        time.sleep(5)

    alias_arn = f"arn:aws:bedrock:{REGION}:{ACCOUNT_ID}:agent-alias/{agent_id}/{alias_id}"
    return alias_id, alias_arn


def allow_bedrock_invoke_lambda(function_name: str, agent_id: str):
    """Add resource-based policy so Bedrock Agent can invoke the Lambda."""
    statement_id = f"bedrock-agent-{agent_id}"
    try:
        lambda_client.add_permission(
            FunctionName=function_name,
            StatementId=statement_id,
            Action="lambda:InvokeFunction",
            Principal="bedrock.amazonaws.com",
            SourceArn=f"arn:aws:bedrock:{REGION}:{ACCOUNT_ID}:agent/{agent_id}",
        )
        print(f"  Lambda permission added: bedrock → {function_name}")
    except lambda_client.exceptions.ResourceConflictException:
        print(f"  Lambda permission already exists for {function_name} — skipping")


# ── Agent Builders ────────────────────────────────────────────────────────────

def create_rag_agent() -> dict:
    print("\n=== Creating RAG Agent ===")
    resp = bedrock.create_agent(
        agentName="techdocs-rag-agent",
        agentResourceRoleArn=AGENT_ROLE_ARN,
        foundationModel=MODEL_ID,
        instruction=read_prompt("rag_agent_system_prompt.md"),
        description="Retrieves relevant document chunks using semantic search (pgvector)",
    )
    agent_id = resp["agent"]["agentId"]
    print(f"  Created agent ID: {agent_id}")

    wait_for_agent(agent_id, "NOT_PREPARED")

    # Allow Bedrock to invoke rag_retriever Lambda
    allow_bedrock_invoke_lambda("rag_retriever", agent_id)

    # Wire action group → rag_retriever Lambda
    print("  Adding action group: rag-search → rag_retriever")
    bedrock.create_agent_action_group(
        agentId=agent_id,
        agentVersion="DRAFT",
        actionGroupName="rag-search",
        description="Semantic search over indexed document chunks",
        actionGroupExecutor={"lambda": LAMBDA_ARN["rag_retriever"]},
        functionSchema={
            "functions": [
                {
                    "name": "retrieve",
                    "description": "Find the most relevant document chunks for a given query using vector similarity search",
                    "parameters": {
                        "query": {
                            "description": "The question or search query to find relevant chunks for",
                            "type": "string",
                            "required": True,
                        },
                        "top_k": {
                            "description": "Number of chunks to return (default 5)",
                            "type": "integer",
                            "required": False,
                        },
                    },
                }
            ]
        },
    )

    alias_id, alias_arn = prepare_and_alias(agent_id, "live")
    print(f"  RAG Agent ready. ID: {agent_id}, Alias: {alias_id}")
    return {"agent_id": agent_id, "alias_id": alias_id, "alias_arn": alias_arn}


def create_data_agent() -> dict:
    print("\n=== Creating Data Agent ===")
    resp = bedrock.create_agent(
        agentName="techdocs-data-agent",
        agentResourceRoleArn=AGENT_ROLE_ARN,
        foundationModel=MODEL_ID,
        instruction=read_prompt("data_agent_system_prompt.md"),
        description="Answers metadata questions about indexed documents (counts, dates, status)",
    )
    agent_id = resp["agent"]["agentId"]
    print(f"  Created agent ID: {agent_id}")

    wait_for_agent(agent_id, "NOT_PREPARED")

    allow_bedrock_invoke_lambda("data_query", agent_id)

    print("  Adding action group: data-query → data_query")
    bedrock.create_agent_action_group(
        agentId=agent_id,
        agentVersion="DRAFT",
        actionGroupName="data-query",
        description="Query document metadata: list docs, count docs, get doc status",
        actionGroupExecutor={"lambda": LAMBDA_ARN["data_query"]},
        functionSchema={
            "functions": [
                {
                    "name": "query",
                    "description": "Query metadata about indexed documents",
                    "parameters": {
                        "query_type": {
                            "description": "Type of query: list_docs, count_docs, or doc_status",
                            "type": "string",
                            "required": True,
                        },
                        "doc_name": {
                            "description": "Document name for doc_status queries (partial match)",
                            "type": "string",
                            "required": False,
                        },
                    },
                }
            ]
        },
    )

    alias_id, alias_arn = prepare_and_alias(agent_id, "live")
    print(f"  Data Agent ready. ID: {agent_id}, Alias: {alias_id}")
    return {"agent_id": agent_id, "alias_id": alias_id, "alias_arn": alias_arn}


def create_synthesis_agent() -> dict:
    print("\n=== Creating Synthesis Agent ===")
    resp = bedrock.create_agent(
        agentName="techdocs-synthesis-agent",
        agentResourceRoleArn=AGENT_ROLE_ARN,
        foundationModel=MODEL_ID,
        instruction=read_prompt("synthesis_agent_system_prompt.md"),
        description="Synthesises results from RAG and Data agents into a final user-facing answer",
    )
    agent_id = resp["agent"]["agentId"]
    print(f"  Created agent ID: {agent_id}")

    wait_for_agent(agent_id, "NOT_PREPARED")

    alias_id, alias_arn = prepare_and_alias(agent_id, "live")
    print(f"  Synthesis Agent ready. ID: {agent_id}, Alias: {alias_id}")
    return {"agent_id": agent_id, "alias_id": alias_id, "alias_arn": alias_arn}


def create_supervisor_agent(rag: dict, data: dict, synthesis: dict) -> dict:
    print("\n=== Creating Supervisor Agent ===")
    resp = bedrock.create_agent(
        agentName="techdocs-supervisor-agent",
        agentResourceRoleArn=AGENT_ROLE_ARN,
        foundationModel=MODEL_ID,
        instruction=read_prompt("supervisor_system_prompt.md"),
        description="Orchestrates RAG, Data, and Synthesis agents to answer user questions",
        # SUPERVISOR mode enables multi-agent collaboration
        agentCollaboration="SUPERVISOR",
    )
    agent_id = resp["agent"]["agentId"]
    print(f"  Created agent ID: {agent_id}")

    wait_for_agent(agent_id, "NOT_PREPARED")

    # Associate collaborators
    for name, info in [("RAG Agent", rag), ("Data Agent", data), ("Synthesis Agent", synthesis)]:
        print(f"  Associating collaborator: {name}")
        bedrock.associate_agent_collaborator(
            agentId=agent_id,
            agentVersion="DRAFT",
            agentDescriptor={"aliasArn": info["alias_arn"]},
            collaborationInstruction=f"Call this agent when you need {name} capabilities",
            collaboratorName=name.replace(" ", ""),  # no spaces allowed
            relayConversationHistory="TO_COLLABORATOR",
        )

    alias_id, alias_arn = prepare_and_alias(agent_id, "live")
    print(f"  Supervisor Agent ready. ID: {agent_id}, Alias: {alias_id}")
    return {"agent_id": agent_id, "alias_id": alias_id, "alias_arn": alias_arn}


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    rag = create_rag_agent()
    data = create_data_agent()
    synthesis = create_synthesis_agent()
    supervisor = create_supervisor_agent(rag, data, synthesis)

    print("\n" + "=" * 60)
    print("ALL AGENTS CREATED — copy these into your .env file:")
    print("=" * 60)
    print(f"SUPERVISOR_AGENT_ID={supervisor['agent_id']}")
    print(f"SUPERVISOR_AGENT_ALIAS_ID={supervisor['alias_id']}")
    print()
    print("For reference:")
    print(f"  RAG Agent:       {rag['agent_id']} / alias: {rag['alias_id']}")
    print(f"  Data Agent:      {data['agent_id']} / alias: {data['alias_id']}")
    print(f"  Synthesis Agent: {synthesis['agent_id']} / alias: {synthesis['alias_id']}")
    print("=" * 60)
