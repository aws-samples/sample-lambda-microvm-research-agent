# Use Python 3.12 as the base runtime
FROM python:3.12-slim

RUN useradd -r -s /sbin/nologin agent

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY agent/ ./agent/
RUN chown -R agent:agent /app

USER agent

# Port 8080 for application traffic (routed from 443 externally)
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python3 -c "import agent" || exit 1

# Lambda calls lifecycle hooks on port 9000
# /ready hook confirms startup — snapshot is taken after this
CMD ["python3", "-m", "agent.main"]
