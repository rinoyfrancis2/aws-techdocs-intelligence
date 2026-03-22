import json
from src.utils.bedrock_client import get_bedrock_runtime

TITAN_MODEL_ID = "amazon.titan-embed-text-v2:0"


def get_embedding(text: str) -> list[float]:
    """Call Titan Embeddings v2 and return a 1024-dim embedding vector."""
    bedrock = get_bedrock_runtime()
    body = json.dumps({"inputText": text})
    response = bedrock.invoke_model(
        modelId=TITAN_MODEL_ID,
        body=body,
        contentType="application/json",
        accept="application/json",
    )
    return json.loads(response["body"].read())["embedding"]
