"""Client configuration adapters; provider keys never belong in client settings."""
import asyncio
import json
import os
from pathlib import Path
import re
import tempfile
import tomllib
import uuid

NAME = 'insta-analyzer'
# title, settings section, relative configuration path, base directory
CLIENTS = {
    'chatgpt': ('ChatGPT — private tunnel', 'tunnel', '', 'home'),
    'cursor': ('Cursor', 'mcpServers', '.cursor/mcp.json', 'home'),
    'claude-desktop': ('Claude Desktop', 'mcpServers', 'Claude/claude_desktop_config.json', 'appdata'),
    'claude-code': ('Claude Code', 'mcpServers', '.mcp.json', 'project'),
    'zed': ('Zed', 'context_servers', 'Zed/settings.json', 'appdata'),
    'vscode': ('VS Code / GitHub Copilot', 'servers', '.vscode/mcp.json', 'project'),
    'codex': ('Codex CLI', 'mcp_servers', '.codex/config.toml', 'home'),
    'gemini': ('Gemini CLI', 'mcpServers', '.gemini/settings.json', 'home'),
    'cline': ('Cline (VS Code extension)', 'mcpServers', 'Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json', 'appdata'),
    'windsurf': ('Windsurf', 'mcpServers', '.codeium/windsurf/mcp_config.json', 'home'),
}


def default_target(client, home=None, appdata=None, project=None):
    _, section, relative, base = CLIENTS[client]
    if section == 'tunnel':
        return None
    home = Path(home or Path.home())
    bases = {'home': home, 'appdata': Path(appdata or os.environ.get('APPDATA', home / 'AppData/Roaming')),
             'project': Path(project) if project else None}
    return bases[base] / relative if bases[base] else None


def server_config(root, port):
    root = Path(root).resolve()
    return {'command': str(root / '.venv/Scripts/python.exe'),
            'args': [str(root / 'mcp-server/mcp_sse_server.py'), '--stdio'],
            'env': {'API_BASE_URL': f'http://127.0.0.1:{port}'}}


def parse_jsonc(text):
    tokens = re.compile(r'"(?:\\.|[^"\\])*"|//[^\r\n]*|/\*[\s\S]*?\*/')
    clean = tokens.sub(lambda m: m[0] if m[0].startswith('"') else re.sub(r'[^\r\n]', ' ', m[0]), text)
    clean = re.sub(r'"(?:\\.|[^"\\])*"|,(\s*[}\]])', lambda m: m[0] if m[1] is None else m[1], clean)
    return json.loads(clean)


def snippet(client, root, port):
    section = CLIENTS[client][1]
    if section == 'tunnel':
        return 'Choose chatgpt mode in Setup; add your private tunnel in ChatGPT.\n'
    server = server_config(root, port)
    if client == 'codex':
        return (f'[{section}.{NAME}]\ncommand = {json.dumps(server["command"])}\n'
                f'args = {json.dumps(server["args"])}\n'
                f'[{section}.{NAME}.env]\nAPI_BASE_URL = {json.dumps(server["env"]["API_BASE_URL"])}\n')
    if client == 'vscode':
        server['type'] = 'stdio'
    return json.dumps({section: {NAME: server}}, indent=2) + '\n'


def merge_text(client, original, root, port):
    section = CLIENTS[client][1]
    if section == 'tunnel':
        raise ValueError('ChatGPT requires Setup tunnel mode, not a local settings file.')
    if client == 'codex':
        start, end = '# BEGIN INSTA ANALYZER MANAGED', '# END INSTA ANALYZER MANAGED'
        if start in original or end in original:
            pattern = re.compile(re.escape(start) + r'\n.*?' + re.escape(end) + r'\n?', re.S)
            if len(pattern.findall(original)) != 1:
                raise ValueError('Invalid managed Codex block. Restore the backup first.')
            original = pattern.sub('', original)
        parsed = tomllib.loads(original)
        if NAME in parsed.get(section, {}):
            raise ValueError('An unmanaged Social Video Analyzer entry exists. Review the exported snippet manually.')
        result = original.rstrip() + '\n\n' + start + '\n' + snippet(client, root, port) + end + '\n'
        tomllib.loads(result)
        return result
    data = parse_jsonc(original) if original.strip() else {}
    if not isinstance(data, dict):
        raise ValueError('Client settings must be an object.')
    servers = data.setdefault(section, {})
    if not isinstance(servers, dict):
        raise ValueError('MCP server section must be an object.')
    new = json.loads(snippet(client, root, port))[section][NAME]
    if NAME in servers and servers[NAME] != new:
        raise ValueError('An existing Social Video Analyzer entry differs. Review the exported snippet manually.')
    servers[NAME] = new
    return json.dumps(data, indent=2, ensure_ascii=False) + '\n'


def install(client, target, root, port):
    target = Path(target).resolve()
    before = target.read_bytes() if target.exists() else None
    result = merge_text(client, before.decode('utf-8-sig') if before else '', root, port).encode('utf-8')
    if before == result:
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    backup = None
    if before is not None:
        backup = target.with_name(target.name + '.insta-backup-' + uuid.uuid4().hex)
        with backup.open('xb') as handle:
            handle.write(before)
    fd, temporary = tempfile.mkstemp(prefix='.insta-', dir=target.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(result)
        if (target.read_bytes() if target.exists() else None) != before:
            raise RuntimeError('Settings changed during installation. Try again.')
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return backup


def export_all(root, port, destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    for client in CLIENTS:
        suffix = '.txt' if client == 'chatgpt' else '.toml' if client == 'codex' else '.json'
        (destination / (client + suffix)).write_text(snippet(client, root, port), encoding='utf-8')
    return destination


async def check_connection(config):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    async with asyncio.timeout(30):
        async with stdio_client(StdioServerParameters(command=config['command'], args=config['args'], env=config['env'])) as streams:
            async with ClientSession(*streams) as session:
                await session.initialize()
                tools = await session.list_tools()
                result = await session.call_tool('get_system_stats', {})
                if result.isError:
                    raise RuntimeError('Backend tool failed. Start services in Setup first.')
                return {'protocol': 'passed', 'backend_tool': 'passed', 'tools': [t.name for t in tools.tools],
                        'inside_application': 'not tested'}


def show_clients(root, port, state):
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    import threading
    window = tk.Toplevel()
    window.title('Social Video Analyzer — AI applications')
    window.geometry('850x540')
    panel = ttk.Frame(window, padding=18)
    panel.pack(fill='both', expand=True)
    ttk.Label(panel, text='Choose an AI application', font=('Segoe UI', 15, 'bold')).pack(anchor='w')
    titles = [c[0] for c in CLIENTS.values()]
    selection = tk.StringVar(value=titles[5])
    combo = ttk.Combobox(panel, textvariable=selection, values=titles, state='readonly')
    combo.pack(fill='x', pady=10)
    target, detected = tk.StringVar(), tk.StringVar()
    ttk.Label(panel, textvariable=detected).pack(anchor='w')
    ttk.Label(panel, text='Configuration file (choose a project for VS Code / Claude Code)').pack(anchor='w', pady=(10, 0))
    ttk.Entry(panel, textvariable=target).pack(fill='x')
    def key():
        return list(CLIENTS)[titles.index(selection.get())]
    def update(*args):
        path = default_target(key())
        target.set(str(path) if path else '')
        detected.set('Existing configuration detected' if path and path.exists() else 'Configuration not found; choose its location or export a snippet')
    combo.bind('<<ComboboxSelected>>', update)
    update()
    def browse():
        if key() == 'chatgpt':
            messagebox.showinfo('ChatGPT', 'Use chatgpt mode in Setup and connect your private tunnel.', parent=window)
            return
        if CLIENTS[key()][3] == 'project':
            folder = filedialog.askdirectory(parent=window, title='Select the project you open in your IDE')
            if folder:
                target.set(str(default_target(key(), project=folder)))
        else:
            path = filedialog.asksaveasfilename(parent=window, title='Client configuration file',
                      initialfile=Path(CLIENTS[key()][2]).name, confirmoverwrite=False)
            if path:
                target.set(path)
    ttk.Button(panel, text='Choose project / configuration…', command=browse).pack(anchor='w', pady=8)
    ttk.Label(panel, text='Applying settings backs up the original beside the file. JSON comments and formatting\nare normalized; unrelated settings and servers are preserved. Restart/reload the client.\nLocal Windows clients only; WSL, SSH and containers need their own runtime.').pack(anchor='w', pady=8)
    status = tk.StringVar(value='Inside application: not tested. Run the independent MCP check below.')
    def apply():
        try:
            if not target.get():
                raise ValueError('Choose a file or project first. ChatGPT uses Setup tunnel mode.')
            backup = install(key(), target.get(), root, port)
            status.set('Configuration applied. ' + ('Backup: ' + str(backup) if backup else 'No previous file changed.') + '\nInside application: not tested.')
        except Exception as exc:
            messagebox.showerror('Client setup', str(exc), parent=window)
    def export():
        os.startfile(export_all(root, port, Path(state) / 'client-configs'))
    def check():
        status.set('Checking MCP and backend; this does not run the selected application…')
        def worker():
            try:
                result = asyncio.run(check_connection(server_config(root, port)))
                message = f'Protocol and backend: passed ({len(result["tools"])} tools). Inside application: not tested.'
            except Exception:
                message = 'Protocol/backend check failed. Start services in Setup, then retry. Check the local logs.'
            window.after(0, lambda: status.set(message))
        threading.Thread(target=worker, daemon=True).start()
    buttons = ttk.Frame(panel)
    buttons.pack(fill='x', pady=10)
    for title, fn in [('Apply with backup', apply), ('Export all snippets', export), ('Check MCP + backend', check)]:
        ttk.Button(buttons, text=title, command=fn).pack(side='left', padx=(0, 8))
    ttk.Label(panel, textvariable=status, wraplength=800).pack(anchor='w')


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['list', 'export', 'install', 'check'])
    parser.add_argument('--client', choices=list(CLIENTS))
    parser.add_argument('--target', type=Path, help='Explicit client configuration file to modify')
    parser.add_argument('--project', type=Path)
    parser.add_argument('--port', type=int, default=18002)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if not 1024 <= args.port <= 65535:
        parser.error('Port must be between 1024 and 65535.')
    if args.action == 'list':
        for key, item in CLIENTS.items():
            path = default_target(key, project=args.project)
            print(f'{key}: {item[0]} | config detected: {bool(path and path.exists())} | {path or "choose project / tunnel setup"}')
    elif args.action == 'export':
        print(export_all(root, args.port, root / '.insta-analyzer/client-configs'))
    elif args.action == 'install':
        if not args.client or not args.target:
            parser.error('Install requires --client and --target; no real client files are modified by default.')
        backup = install(args.client, args.target, root, args.port)
        print('Applied. Backup: ' + (str(backup) if backup else 'none needed'))
    else:
        print(json.dumps(asyncio.run(check_connection(server_config(root, args.port))), indent=2))


if __name__ == '__main__':
    main()
