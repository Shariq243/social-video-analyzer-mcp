#!/usr/bin/env python3
"""
Social Video Analyzer - MCP SSE Server
HTTP/SSE transport for online MCP access

This server exposes the MCP protocol over HTTP with Server-Sent Events (SSE)
allowing remote clients to connect and use MCP tools over the internet.
"""

import asyncio
import json
import logging
import os
import sys
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse
from dotenv import load_dotenv
from starlette.routing import Route
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from typing import Any, Dict, Optional, List
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Depends, Header, Request
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.types import (
    Tool,
    TextContent,
    ImageContent,
    EmbeddedResource,
    CallToolResult,
    ListToolsResult,
    ListResourcesResult,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Configuration: process environment takes precedence; never load backend secrets here.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
from video_platforms import platform_for_url
load_dotenv(PROJECT_ROOT / ".env.local")
load_dotenv(Path(__file__).with_name(".env.sse"))
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
MCP_SERVER_PORT = int(os.getenv("MCP_SERVER_PORT", "8100"))
API_KEYS = [key.strip() for key in os.getenv("MCP_API_KEYS", "").split(",") if key.strip()]  # Comma-separated API keys
REQUEST_TIMEOUT = 300.0

# In-memory session storage (use Redis in production)
active_sessions: Dict[str, Dict[str, Any]] = {}

# HTTP client
http_client: Optional[httpx.AsyncClient] = None


# ============================================================================
# AUTHENTICATION
# ============================================================================

class AuthToken(BaseModel):
    """API token for authentication"""
    token: str = Field(description="Bearer token for API authentication")


def generate_api_key() -> str:
    """Generate a secure API key"""
    return secrets.token_urlsafe(32)


async def verify_api_key(authorization: str = Header(None)) -> str:
    """Verify API key from Authorization header"""
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid Authorization format")

    token = authorization[7:]  # Remove "Bearer " prefix

    # Check if token is valid
    if not any(secrets.compare_digest(token, key) for key in API_KEYS):
        raise HTTPException(status_code=401, detail="Invalid API key")

    return token


# ============================================================================
# FASTAPI APPLICATION
# ============================================================================

def backend_headers():
    key = os.getenv("BACKEND_API_KEY", "")
    root = Path(__file__).resolve().parents[1]
    if not key and (root / ".insta-analyzer/credentials.dpapi").exists():
        import sys
        sys.path.insert(0, str(root / "windows"))
        from launcher import load_settings
        key = load_settings(root / '.insta-analyzer').backend_key
    return {"X-Insta-Backend-Key": key} if key else {}


def create_backend_client(base_url: str, **options) -> httpx.AsyncClient:
    loopback = urlparse(base_url).hostname in {"localhost", "127.0.0.1", "::1"}
    return httpx.AsyncClient(
        base_url=base_url, headers=backend_headers(), trust_env=not loopback, **options
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    global http_client

    if not API_KEYS:
        raise RuntimeError("MCP_API_KEYS must contain at least one non-empty key")
    logger.info("Starting authenticated MCP server")

    # Initialize HTTP client
    http_client = create_backend_client(
        API_BASE_URL,
        timeout=httpx.Timeout(REQUEST_TIMEOUT),
        limits=httpx.Limits(max_connections=50, max_keepalive_connections=20)
    )

    # Test API connection
    try:
        response = await http_client.get("/health")
        if response.status_code == 200:
            logger.info(f"✅ Connected to backend API at {API_BASE_URL}")
        else:
            logger.warning(f"⚠️ Backend API responded with status {response.status_code}")
    except Exception as e:
        logger.error(f"❌ Failed to connect to backend API: {e}")

    async with http_manager.run():
        yield

    # Cleanup
    logger.info("🔄 Shutting down MCP SSE Server...")
    if http_client:
        await http_client.aclose()
    logger.info("✅ Server shutdown complete")


app = FastAPI(
    title="Social Video Analyzer MCP Server",
    description="MCP server for Instagram, Facebook, X, LinkedIn and TikTok video analysis",
    version="2.0.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8100", "http://127.0.0.1:8100"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# MCP TOOL IMPLEMENTATIONS
# ============================================================================

async def analyze_video_tool(url: str, analysis_type: str = "comprehensive", wait: bool = False, *, analyze_post: bool = False) -> Dict[str, Any]:
    """Analyze an Instagram video"""
    logger.info("Submitting media analysis")

    # Validate analysis type
    valid_types = ["comprehensive", "summary", "transcription", "visual_description"]
    if analysis_type not in valid_types:
        raise ValueError(f"Invalid analysis_type. Must be one of: {', '.join(valid_types)}")

    platform_for_url(url)

    # Make API request
    payload = {
        "instagram_url": url,
        "analysis_type": analysis_type
    }

    if analyze_post:
        payload["analyze_post"] = True
    response = await http_client.post("/api/video/analyze", json=payload)

    if response.status_code == 200:
        result = response.json()
        job_id = result.get("job_id")

        if not wait:
            return {"success": True, **result, "next_step": "Call get_job_status with this job_id until completed or failed."}

        # Wait for completion
        logger.info(f"⏳ Waiting for analysis completion: {job_id}")
        final_status = await wait_for_completion(job_id)
        if analyze_post:
            return {"success": True, **final_status}

        return {
            "success": True,
            "job_id": job_id,
            "status": "completed",
            "analysis": final_status.get("analysis_result", {})
        }
    else:
        raise Exception(f"API error: {response.status_code} - {response.text}")


async def get_job_status_tool(job_id: str) -> Dict[str, Any]:
    """Get job status"""
    response = await http_client.get(f"/api/video/status/{job_id}")

    if response.status_code == 200:
        return response.json()
    else:
        raise Exception(f"API error: {response.status_code}")


async def list_recent_analyses_tool(limit: int = 10, page: int = 1) -> Dict[str, Any]:
    """List recent analyses"""
    params = {"per_page": limit, "page": page}
    response = await http_client.get("/api/jobs/", params=params)

    if response.status_code == 200:
        return response.json()
    else:
        raise Exception(f"API error: {response.status_code}")


async def cancel_job_tool(job_id: str) -> Dict[str, Any]:
    """Cancel a job"""
    response = await http_client.post(f"/api/jobs/{job_id}/cancel")

    if response.status_code == 200:
        return {"success": True, "message": "Job cancelled successfully"}
    else:
        raise Exception(f"API error: {response.status_code}")


async def get_system_stats_tool() -> Dict[str, Any]:
    """Get system statistics"""
    response = await http_client.get("/api/jobs/stats")

    if response.status_code == 200:
        return response.json()
    else:
        raise Exception(f"API error: {response.status_code}")


async def wait_for_completion(job_id: str, max_wait: int = 300) -> Dict[str, Any]:
    """Wait for job completion"""
    waited = 0
    while waited < max_wait:
        response = await http_client.get(f"/api/video/status/{job_id}")

        if response.status_code == 200:
            status_data = response.json()
            status = status_data.get("status")

            if status == "completed":
                return status_data
            elif status == "failed":
                error = status_data.get("error_message", "Unknown error")
                raise Exception(f"Analysis failed: {error}")

            if status == "cancelled":
                raise ValueError("Analysis was cancelled")
            await asyncio.sleep(5)
            waited += 5
        else:
            raise Exception(f"Status check error: {response.status_code}")

    raise Exception("Timeout waiting for analysis completion")


# ============================================================================
# MCP SERVER SETUP
# ============================================================================

def create_mcp_server() -> Server:
    """Create and configure MCP server"""
    server = Server("instagram-video-analyzer")

    # Register tools
    @server.list_tools()
    async def list_tools() -> List[Tool]:
        tools = [
            Tool(
                name="analyze_instagram_video",
                description="Analyze a public video from Instagram, Facebook, TikTok, LinkedIn, or X (Twitter) using AI. Returns a job_id promptly; call get_job_status until completed or failed, then read analysis_result.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "Public HTTPS video URL from Instagram, Facebook, TikTok, LinkedIn, or X (Twitter)"
                        },
                        "analysis_type": {
                            "type": "string",
                            "enum": ["comprehensive", "summary", "transcription", "visual_description"],
                            "description": "Type of analysis",
                            "default": "comprehensive"
                        },
                        "wait": {"type": "boolean", "default": False, "description": "Wait up to 300 seconds. Keep false with Secure MCP Tunnel (120 second deadline)."}
                    },
                    "required": ["url"]
                }
            ),
            Tool(
                name="get_job_status",
                description="Get the status of an analysis job",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "job_id": {
                            "type": "string",
                            "description": "Job ID to check"
                        }
                    },
                    "required": ["job_id"]
                }
            ),
            Tool(
                name="list_recent_analyses",
                description="List recent video analyses",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of results",
                            "default": 10
                        },
                        "page": {
                            "type": "integer",
                            "description": "Page number",
                            "default": 1
                        }
                    }
                }
            ),
            Tool(
                name="cancel_job",
                description="Cancel a running analysis job",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "job_id": {
                            "type": "string",
                            "description": "Job ID to cancel"
                        }
                    },
                    "required": ["job_id"]
                }
            ),
            Tool(
                name="get_system_stats",
                description="Get system performance statistics",
                inputSchema={
                    "type": "object",
                    "properties": {}
                }
            )
        ]

        video_schema = tools[0].inputSchema
        post_schema = {**video_schema, "properties": {**video_schema["properties"],
            "url": {"type": "string", "description": "Public HTTPS post URL on Instagram, Facebook, TikTok, LinkedIn, or X"}}}
        tools.insert(1, Tool(
            name="analyze_instagram_post",
            description=("Analyze public posts across Instagram, Facebook, TikTok, LinkedIn and X. "
                         "Supports Instagram images, videos and ordered carousels. Other platforms support "
                         "videos and accessible public preview images. Transcription requires video audio. "
                         "Returns a job ID for get_job_status."),
            inputSchema=post_schema,
        ))
        return tools

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> List[TextContent | ImageContent | EmbeddedResource]:
        """Handle tool calls"""
        try:
            if name in {"analyze_instagram_video", "analyze_instagram_post"}:
                result = await analyze_video_tool(
                    arguments.get("url"),
                    arguments.get("analysis_type", "comprehensive"),
                    arguments.get("wait", False),
                    analyze_post=name == "analyze_instagram_post",
                )
            elif name == "get_job_status":
                result = await get_job_status_tool(arguments.get("job_id"))
            elif name == "list_recent_analyses":
                result = await list_recent_analyses_tool(
                    arguments.get("limit", 10),
                    arguments.get("page", 1)
                )
            elif name == "cancel_job":
                result = await cancel_job_tool(arguments.get("job_id"))
            elif name == "get_system_stats":
                result = await get_system_stats_tool()
            else:
                raise ValueError(f"Unknown tool: {name}")

            return [TextContent(
                type="text",
                text=json.dumps(result, indent=2, ensure_ascii=False)
            )]
        except Exception as e:
            logger.error(f"Error executing tool {name}: {e}")
            return CallToolResult(isError=True, content=[TextContent(
                type="text", text=json.dumps({"error": str(e)}, indent=2)
            )])

    return server


# ============================================================================
# API ENDPOINTS
# ============================================================================

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "name": "Social Video Analyzer MCP Server",
        "version": "2.0.0",
        "transport": "SSE and Streamable HTTP",
        "backend": API_BASE_URL,
        "endpoints": {
            "sse": "/sse",
            "mcp": "/mcp",
            "health": "/health",
            "generate_key": "/generate-key"
        }
    }


@app.get("/health")
async def health():
    """Health check endpoint"""
    # Check backend connection
    backend_healthy = False
    try:
        response = await http_client.get("/health", timeout=5.0)
        backend_healthy = response.status_code == 200
    except:
        pass

    return {
        "status": "healthy" if backend_healthy else "degraded",
        "backend": "connected" if backend_healthy else "disconnected",
        "timestamp": datetime.utcnow().isoformat()
    }


@app.post("/generate-key")
async def generate_key(token: str = Depends(verify_api_key)):
    """Generate a new API key (admin only)"""
    new_key = generate_api_key()
    return {
        "api_key": new_key,
        "note": "Add this key to MCP_API_KEYS environment variable"
    }


# ASGI endpoints must receive scope, receive AND send. Both SSE routes share
# the same transport, which owns and dispatches session messages.
mcp_server = create_mcp_server()
security_settings = TransportSecuritySettings(
    allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*"],
    allowed_origins=["http://127.0.0.1:*", "http://localhost:*"],
)
sse_transport = SseServerTransport("/messages", security_settings=security_settings)
http_manager = StreamableHTTPSessionManager(
    mcp_server, stateless=True, json_response=True, security_settings=security_settings,
)

class AuthenticatedASGI:
    def __init__(self, handler):
        self.handler = handler

    async def __call__(self, scope, receive, send):
        headers = dict(scope.get("headers", []))
        authorization = headers.get(b"authorization", b"").decode("latin-1")
        try:
            await verify_api_key(authorization)
        except HTTPException:
            response = JSONResponse({"detail": "Unauthorized"}, status_code=401,
                                    headers={"WWW-Authenticate": "Bearer"})
            await response(scope, receive, send)
            return
        await self.handler(scope, receive, send)

async def handle_sse(scope, receive, send):
    async with sse_transport.connect_sse(scope, receive, send) as streams:
        await mcp_server.run(*streams, mcp_server.create_initialization_options())

app.router.routes.extend([
    Route("/sse", endpoint=AuthenticatedASGI(handle_sse), methods=["GET"]),
    Route("/messages", endpoint=AuthenticatedASGI(sse_transport.handle_post_message), methods=["POST"]),
    Route("/mcp", endpoint=AuthenticatedASGI(http_manager.handle_request), methods=["GET", "POST", "DELETE"]),
])


@app.get("/sessions")
async def list_sessions(token: str = Depends(verify_api_key)):
    """List active sessions (admin only)"""
    return {
        "active_sessions": len(active_sessions),
        "sessions": [
            {
                "session_id": sid,
                "created_at": data["created_at"].isoformat(),
                "client_ip": data["client_ip"]
            }
            for sid, data in active_sessions.items()
        ]
    }


# ============================================================================
# MAIN
# ============================================================================

def main():
    """Run the MCP SSE server"""
    import uvicorn

    logger.info("🚀 Starting Social Video Analyzer MCP SSE Server")
    logger.info(f"📡 Backend API: {API_BASE_URL}")
    logger.info(f"🔒 Authentication: {'Enabled' if API_KEYS else 'Disabled (WARNING!)'}")
    logger.info(f"🌐 Server will listen on: http://127.0.0.1:{MCP_SERVER_PORT}")

    if not API_KEYS or API_KEYS == ['']:
        logger.warning("⚠️  WARNING: No API keys configured! Set MCP_API_KEYS environment variable")
        logger.warning("⚠️  Generate keys with: curl -X POST http://localhost:8100/generate-key")

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=MCP_SERVER_PORT,
        log_level="info"
    )


if __name__ == "__main__":
    import sys
    if "--stdio" in sys.argv:
        from mcp.server.stdio import stdio_server

        async def run_stdio():
            global http_client
            async with create_backend_client(API_BASE_URL, timeout=REQUEST_TIMEOUT) as client:
                http_client = client
                async with stdio_server() as streams:
                    await mcp_server.run(*streams, mcp_server.create_initialization_options())
        asyncio.run(run_stdio())
    else:
        main()
