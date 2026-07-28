"""Agent configuration loaded from environment variables."""
import os

AGENT_TASK = os.environ.get("AGENT_TASK", "Research the topic")
S3_BUCKET = os.environ.get("S3_BUCKET", "")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
BEDROCK_MODEL_ID = os.environ.get(
    "BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-6"
)
BEDROCK_FAST_MODEL_ID = os.environ.get(
    "BEDROCK_FAST_MODEL_ID", "us.anthropic.claude-haiku-4-5-20251001-v1:0"
)
MAX_STEPS = int(os.environ.get("MAX_STEPS", "5"))

# AgentCore Gateway URL for web search (MCP endpoint)
AGENTCORE_GATEWAY_URL = os.environ.get("AGENTCORE_GATEWAY_URL", "")
