"""Amazon Bedrock integration for LLM-powered reasoning."""
import json
import boto3
from botocore.config import Config
from agent.config import AWS_REGION, BEDROCK_MODEL_ID, BEDROCK_FAST_MODEL_ID

bedrock = boto3.client(
    "bedrock-runtime",
    region_name=AWS_REGION,
    config=Config(read_timeout=120, connect_timeout=10, retries={"max_attempts": 2}),
)


def call_bedrock(prompt: str, system: str = "", fast: bool = False) -> str:
    """Call Amazon Bedrock Claude for reasoning.

    Args:
        prompt: The user message to send.
        system: Optional system prompt for role instructions.
        fast: Use the faster (Haiku) model for simpler tasks like synthesis.

    Returns:
        The model's text response.
    """
    model_id = BEDROCK_FAST_MODEL_ID if fast else BEDROCK_MODEL_ID
    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 4096 if fast else 8192,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        body["system"] = system

    response = bedrock.invoke_model(
        modelId=model_id,
        body=json.dumps(body),
    )
    result = json.loads(response["body"].read())
    return result["content"][0]["text"]
