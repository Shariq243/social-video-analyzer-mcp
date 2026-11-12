"""Exercise real MCP discovery, authentication, and backend calls without showing keys."""
import argparse
import asyncio
import json
import os
import sys
from datetime import timedelta
from pathlib import Path

import httpx
from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / '.env.local')
load_dotenv(ROOT / 'mcp-server' / '.env.sse')

async def check_session(streams, label, analyze_url=None):
    async with ClientSession(streams[0], streams[1], read_timeout_seconds=timedelta(seconds=30)) as session:
        await session.initialize()
        names = {t.name for t in (await session.list_tools()).tools}
        assert names == {'analyze_instagram_video', 'get_job_status', 'list_recent_analyses', 'cancel_job', 'get_system_stats'}
        for name, args in [('get_system_stats', {}), ('list_recent_analyses', {'limit': 1})]:
            result = await session.call_tool(name, args)
            assert not result.isError, name + ' could not reach backend'
        invalid = await session.call_tool('analyze_instagram_video', {'url': 'https://example.com/instagram.com/reel/fake/'})
        assert invalid.isError
        print(label + ': initialized, MCP tools discovered, backend calls passed, invalid URL rejected', flush=True)
        if analyze_url:
            result = await session.call_tool('analyze_instagram_video', {'url': analyze_url, 'analysis_type': 'summary'})
            assert not result.isError, 'Analysis submission failed'
            job = json.loads(result.content[0].text)
            print('Analysis job accepted: ' + job['job_id'], flush=True)
            for _ in range(100):
                result = await session.call_tool('get_job_status', {'job_id': job['job_id']})
                assert not result.isError
                data = json.loads(result.content[0].text)
                if data['status'] == 'completed':
                    assert data.get('analysis_result')
                    print('REAL INSTAGRAM ANALYSIS COMPLETED; result saved by backend.', flush=True)
                    return
                if data['status'] in {'failed', 'cancelled'}:
                    raise RuntimeError('Analysis ' + data['status'] + '; inspect private backend logs for details')
                await asyncio.sleep(3)
            raise TimeoutError('Analysis still processing; use get_job_status with the printed job ID')

async def main(args):
    key = os.environ.get('MCP_API_KEYS', '').split(',')[0].strip()
    assert key, 'MCP_API_KEYS must be configured locally'
    headers = {'Authorization': 'Bearer ' + key}
    async with httpx.AsyncClient(timeout=30) as client:
        for path, method in [('/sse', 'GET'), ('/messages', 'POST'), ('/mcp', 'POST')]:
            for auth in [{}, {'Authorization': 'Bearer invalid-test-credential'}]:
                r = await client.request(method, args.base_url + path, headers=auth)
                assert r.status_code == 401, 'Unauthenticated transport was accepted'
        health = await client.get(args.base_url + '/health')
        assert health.json()['backend'] == 'connected'
    print('Authentication: missing and invalid credentials rejected on all transports', flush=True)
    async with sse_client(args.base_url + '/sse', headers=headers) as streams:
        await check_session(streams, 'SSE')
    async with httpx.AsyncClient(headers=headers, timeout=30) as client:
        async with streamable_http_client(args.base_url + '/mcp', http_client=client) as streams:
            await check_session(streams, 'Streamable HTTP', args.analyze)
    if args.stdio:
        env = dict(os.environ, API_BASE_URL=args.backend_url)
        params = StdioServerParameters(command=sys.executable, args=[str(ROOT / 'mcp-server' / 'mcp_sse_server.py'), '--stdio'], env=env)
        async with stdio_client(params) as streams:
            await check_session(streams, 'Tunnel stdio')

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', default='http://127.0.0.1:8100')
    parser.add_argument('--backend-url', default='http://127.0.0.1:8000')
    parser.add_argument('--stdio', action='store_true')
    parser.add_argument('--analyze', metavar='INSTAGRAM_URL')
    asyncio.run(main(parser.parse_args()))
