"""Research Agent — session-based autonomous ReAct loop on Lambda MicroVMs."""
import json
import logging
import uuid
from datetime import datetime, timezone

from agent.config import AGENT_TASK, S3_BUCKET, MAX_STEPS

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a research agent. You autonomously search the web and \
read pages to gather information, then produce a structured report.

You have access to the conversation history from this session. Use it to provide \
continuity — if the user asks a follow-up, build on what you already found.

You MUST respond with valid JSON in one of these formats:
- {"type": "search", "query": "your search query"}
- {"type": "browse", "url": "https://..."}
- {"type": "finish", "report": "your final markdown report"}

Think step by step about what information you still need before finishing."""


class ResearchSession:
    """Manages a research session with conversation history."""

    def __init__(self, session_id: str = None):
        self.session_id = session_id or str(uuid.uuid4())
        self.history: list = []  # [{role, content, timestamp}]
        self.all_findings: list = []  # accumulated across requests
        self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "history": self.history,
            "findings_count": len(self.all_findings),
            "created_at": self.created_at,
        }


class ResearchAgent:
    """Autonomous research agent using the ReAct pattern with session memory."""

    def __init__(self, task: str, session: ResearchSession = None):
        import boto3
        self.task = task
        self.session = session or ResearchSession()
        self.memory: list = []
        self.max_steps = MAX_STEPS
        self.s3 = boto3.client("s3")

    def run(self) -> str:
        """Main ReAct loop — runs until task is complete or max steps reached."""
        logger.info(f"Starting research: {self.task}")

        # Add user message to session history
        self.session.history.append({
            "role": "user",
            "content": self.task,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        for step in range(self.max_steps):
            logger.info(f"Step {step + 1}/{self.max_steps}")

            action = self._reason()

            if action is None:
                logger.warning("Failed to parse LLM response, retrying...")
                continue

            if action["type"] == "finish":
                report = action.get("report", "")
                self._save_results(report)
                self.session.history.append({
                    "role": "assistant",
                    "content": report,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
                self.session.all_findings.extend(self.memory)
                logger.info("Research complete.")
                return report

            result = self._act(action)
            self.memory.append({"step": step, "action": action, "result": result})
            logger.info(f"Completed action: {action['type']}")

        # Max steps reached — synthesize
        logger.info("Max steps reached, synthesizing findings...")
        report = self._synthesize()
        logger.info(f"Synthesis complete, report length: {len(report)} chars")
        self._save_results(report)
        logger.info("Results saved to S3")
        self.session.history.append({
            "role": "assistant",
            "content": report,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        self.session.all_findings.extend(self.memory)
        return report

    def _reason(self) -> "dict | None":
        """Call Bedrock to decide the next action."""
        from agent.llm import call_bedrock

        # Include session context for follow-ups (sliding window: last 6 messages)
        session_context = ""
        if len(self.session.history) > 1:
            recent_history = self.session.history[-6:]  # Keep last 6 messages
            older_count = len(self.session.history) - len(recent_history) - 1

            if older_count > 0:
                session_context = f"""
This session has {len(self.session.history)} messages total. Showing the most recent {len(recent_history)}:
{json.dumps(recent_history, indent=2, default=str)}

Summary: {older_count} older messages were exchanged earlier in this session.
Previous research topics covered: {len(self.session.all_findings)} findings collected.

"""
            else:
                session_context = f"""
Previous conversation in this session:
{json.dumps(self.session.history[:-1], indent=2, default=str)}

"""

        # Only include last 3 findings for context, truncated
        recent_findings = self.session.all_findings[-3:]
        findings_context = ""
        if recent_findings:
            truncated = []
            for f in recent_findings:
                result = str(f.get("result", ""))[:500]
                truncated.append({"action": f.get("action"), "result": result})
            findings_context = f"Recent findings from earlier requests:\n{json.dumps(truncated, indent=2, default=str)}\n\n"

        prompt = f"""{session_context}{findings_context}Current research task: {self.task}

Findings so far this request ({len(self.memory)} steps completed):
{json.dumps(self.memory[-5:], indent=2, default=str)}

Decide your next action. Respond with ONLY valid JSON."""

        response = call_bedrock(prompt, system=SYSTEM_PROMPT)

        try:
            text = response.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            return json.loads(text)
        except json.JSONDecodeError:
            # Handle truncated finish responses — if it starts with a finish type,
            # extract whatever report content we can
            if '"type": "finish"' in response or '"type":"finish"' in response:
                logger.warning("Truncated finish response detected, extracting partial report")
                # Extract report content after "report": "
                report_start = response.find('"report"')
                if report_start != -1:
                    # Find the start of the report value
                    colon_pos = response.find(':', report_start)
                    # Skip whitespace and opening quote
                    content_start = response.find('"', colon_pos + 1) + 1
                    report_content = response[content_start:]
                    # Clean up trailing incomplete content
                    report_content = report_content.rstrip('"}\n\r ')
                    return {"type": "finish", "report": report_content}
            logger.error(f"Invalid JSON from LLM: {response[:200]}")
            return None

    def _act(self, action: dict) -> str:
        """Execute the chosen tool."""
        from agent.tools import browse_url, search_web
        if action["type"] == "search":
            results = search_web(action["query"])
            return json.dumps(results, default=str)
        elif action["type"] == "browse":
            return browse_url(action["url"])
        else:
            return f"Unknown action type: {action['type']}"

    def _synthesize(self) -> str:
        """Generate final report from collected findings."""
        from agent.llm import call_bedrock

        # Truncate findings to avoid exceeding model context window
        truncated_memory = []
        for item in self.memory:
            entry = {"step": item.get("step"), "action": item.get("action")}
            result = item.get("result", "")
            # Limit each result to 2000 chars to keep total payload manageable
            if len(result) > 2000:
                result = result[:2000] + "\n... [truncated]"
            entry["result"] = result
            truncated_memory.append(entry)

        prompt = f"""Based on these research findings:
{json.dumps(truncated_memory, indent=2, default=str)}

Write a comprehensive, structured markdown report answering: {self.task}

Include:
- Executive summary
- Key findings with details
- Sources referenced
- Conclusions"""

        logger.info(f"Calling Bedrock (fast) for synthesis, prompt length: {len(prompt)} chars")
        report = call_bedrock(prompt, system="You are a research report writer.", fast=True)
        logger.info(f"Bedrock synthesis returned {len(report)} chars")
        return report

    def _save_results(self, report: str):
        """Write results to S3."""
        import re
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        safe_task = re.sub(r"[^a-zA-Z0-9_\-]", "_", self.task[:40])
        key = f"reports/{self.session.session_id}/{timestamp}_{safe_task}.json"
        try:
            self.s3.put_object(
                Bucket=S3_BUCKET,
                Key=key,
                Body=json.dumps({
                    "session_id": self.session.session_id,
                    "task": self.task,
                    "report": report,
                    "steps": len(self.memory),
                    "timestamp": timestamp,
                }),
                ContentType="application/json",
            )
            logger.info(f"Results saved to s3://{S3_BUCKET}/{key}")
        except Exception as e:
            logger.error(f"Failed to save results to S3: {e}")


# ─── HTTP Server ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import os
    import http.server
    import threading

    _HOOKS_PORT = 9000
    _APP_PORT = 8080
    _microvm_id = None

    # In-memory session store (lives as long as the MicroVM)
    _sessions: dict[str, ResearchSession] = {}

    # ─── Lifecycle Hooks (port 9000) ────────────────────────────────────────────

    class LifecycleHookHandler(http.server.BaseHTTPRequestHandler):
        """Lambda MicroVM lifecycle hooks on port 9000."""

        def do_POST(self):
            global _microvm_id
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length) if content_length else b""

            if "/ready" in self.path:
                logger.info("Hook: /ready — app initialized")
            elif "/run" in self.path:
                try:
                    data = json.loads(body)
                    _microvm_id = data.get("microvmId")
                    logger.info(f"Hook: /run — microvmId={_microvm_id}")
                except (json.JSONDecodeError, TypeError):
                    pass
            elif "/suspend" in self.path:
                logger.info("Hook: /suspend")
            elif "/resume" in self.path:
                logger.info("Hook: /resume")
            elif "/terminate" in self.path:
                logger.info("Hook: /terminate")

            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *a):
            """Suppress default HTTP logging."""

    # ─── Application Server (port 8080) ─────────────────────────────────────────

    class ResearchHandler(http.server.BaseHTTPRequestHandler):
        """Research agent HTTP service on port 8080."""

        def _send_json(self, status: int, data: dict):
            body = json.dumps(data).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-aws-proxy-auth")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self):
            """Handle CORS preflight."""
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-aws-proxy-auth")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_POST(self):
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length) if content_length else b""

            if "/research" in self.path:
                try:
                    data = json.loads(body)
                    task = data.get("task", AGENT_TASK)
                    session_id = data.get("sessionId", None)
                    gateway_url = data.get("gatewayUrl", "")

                    if gateway_url:
                        os.environ["AGENTCORE_GATEWAY_URL"] = gateway_url

                    # Get or create session
                    if session_id and session_id in _sessions:
                        session = _sessions[session_id]
                        logger.info(f"Continuing session {session_id} ({len(session.history)} messages)")
                    else:
                        session = ResearchSession()
                        _sessions[session.session_id] = session
                        logger.info(f"New session created: {session.session_id}")

                    logger.info(f"=== RESEARCH REQUEST: {task} ===")
                    agent = ResearchAgent(task, session=session)
                    result = agent.run()
                    logger.info("=== RESEARCH COMPLETE ===")

                    self._send_json(200, {
                        "success": True,
                        "sessionId": session.session_id,
                        "task": task,
                        "report": result,
                        "messagesInSession": len(session.history),
                    })

                except Exception as e:
                    logger.error(f"Research failed: {e}")
                    self._send_json(500, {"success": False, "error": str(e)})

            elif "/sessions" in self.path:
                # List active sessions
                sessions_list = [
                    {**s.to_dict(), "messages": len(s.history)}
                    for s in _sessions.values()
                ]
                self._send_json(200, {"sessions": sessions_list})

            elif "/health" in self.path:
                self._send_json(200, {
                    "service": "research-agent",
                    "microvm_id": _microvm_id,
                    "status": "ready",
                    "active_sessions": len(_sessions),
                })
            else:
                self._send_json(404, {"error": "Not found"})

        def do_GET(self):
            if "/sessions" in self.path:
                sessions_list = [
                    {**s.to_dict(), "messages": len(s.history)}
                    for s in _sessions.values()
                ]
                self._send_json(200, {"sessions": sessions_list})
            elif "/health" in self.path:
                self._send_json(200, {
                    "service": "research-agent",
                    "microvm_id": _microvm_id,
                    "status": "ready",
                    "active_sessions": len(_sessions),
                })
            else:
                self._send_json(200, {
                    "service": "research-agent",
                    "microvm_id": _microvm_id,
                    "status": "ready",
                })

        def log_message(self, *a):
            """Suppress default HTTP logging."""

    # Start lifecycle hooks server (port 9000)
    hooks_server = http.server.HTTPServer(("0.0.0.0", _HOOKS_PORT), LifecycleHookHandler)  # nosec B104
    threading.Thread(target=hooks_server.serve_forever, daemon=True).start()
    logger.info(f"Lifecycle hooks server on port {_HOOKS_PORT}")

    # Start application server (port 8080)
    app_server = http.server.HTTPServer(("0.0.0.0", _APP_PORT), ResearchHandler)  # nosec B104
    logger.info(f"Research agent service on port {_APP_PORT}")
    logger.info("Ready — POST /research with {task, sessionId?}")

    # Block on serving
    app_server.serve_forever()
