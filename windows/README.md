# Insta Analyzer for Windows

This is a Windows installer and automatic startup companion for the existing
[Instagram Video Analyzer MCP](https://github.com/Morfeu333/instagram-video-analyzer-mcp).
The original MIT license and attribution are preserved.

Security update: the backend now requires an automatically generated internal
credential, checks Host/Origin, redacts all backend log handlers, and bounds jobs
and media downloads. See [security and upgrade instructions](SECURITY.md).
When updating an existing installation, stop its services, update the source,
run Setup and Save/start, then restart your AI client. Existing keys are kept.

## Choose your application

Step-by-step guides: [ChatGPT](docs/clients/chatgpt.md),
[Cursor](docs/clients/cursor.md), [Claude Desktop](docs/clients/claude-desktop.md),
[Claude Code](docs/clients/claude-code.md), [Zed](docs/clients/zed.md),
[VS Code / GitHub Copilot](docs/clients/vscode.md), [Codex CLI](docs/clients/codex.md),
[Gemini CLI](docs/clients/gemini.md), [Cline](docs/clients/cline.md),
[Windsurf](docs/clients/windsurf.md).

These links are relative to the release's root README. When reading this file
inside `windows/`, open `../docs/clients/` instead.

## Windows compatibility

The installer targets **Windows 10 and Windows 11, x64**, with Windows PowerShell
5.1 or later and internet access. Use an up-to-date Windows 10 installation
(22H2 recommended). Python 3.13 supports Windows 10; the launcher uses Windows
DPAPI, registry login startup, and Job Objects available on both versions.
No Windows 11-only API is required. ARM64-native and 32-bit installs are not supported.

Windows 11 has been tested here. Windows 10 compatibility is based on the runtime
requirements and API review; a real Windows 10 machine has **not yet been tested**.
Each AI application's own current OS, GPU, subscription, and account requirements
also apply. See [Python Windows requirements](https://docs.python.org/3.13/using/windows.html).

## Install once

1. Download the source ZIP and extract it to a permanent folder you own.
2. Double-click **Setup.cmd** at the repository root. It installs a private Python
   environment, dependencies, and the official OpenAI tunnel client. Internet
   access is needed for installation and analysis. Windows 10/11 x64 is targeted;
   no administrator privileges or global Python installation are required.
3. For ChatGPT, choose **chatgpt** mode. Enter **your own** Google Gemini API key, OpenAI tunnel runtime API key, and
   OpenAI tunnel ID in the setup window. Leave automatic startup checked.
   Click **Save and start** and wait for **Ready**.
4. Once, add the private MCP server in ChatGPT: **Plugins → Add custom MCP server
   → Connection: Tunnel → your tunnel ID → No authentication**. Create it privately,
   install it, and enable it in the conversation.

Create a tunnel in [OpenAI Platform](https://platform.openai.com/settings/organization/tunnels),
associated with your intended ChatGPT workspace. The runtime key's principal
needs **Tunnels Read + Use**. Create a runtime key in
[API keys](https://platform.openai.com/settings/organization/api-keys), not an admin key.
Get the separate Gemini key from [Google AI Studio](https://aistudio.google.com/apikey).
These accounts and their access requirements remain necessary. This installer
does not create accounts, bypass permissions, or install a directory-listed plugin.

If you previously started services manually, close those backend/tunnel terminal
windows with Ctrl+C before switching to automatic mode. They use the same ports.
The previously configured ChatGPT plugin can be reused with the same tunnel ID.

## Cursor, Claude Desktop / Claude Code, and Zed

Choose **local** mode (the default) in Setup. Enter only **your own Gemini key**,
leave automatic startup enabled, and click **Save and start**. No OpenAI account,
runtime key, or tunnel is needed in this mode.

Click **Set up AI applications (10 clients)**. Choose an application and its
configuration file or project, then **Apply with backup**. Or choose **Export all
snippets** for manual integration. Generated files are in ignored
`.insta-analyzer/client-configs` and contain no provider keys.

- Cursor: `.cursor/mcp.json` in your project, or your user MCP settings.
- Claude Desktop: `%APPDATA%/Claude/claude_desktop_config.json`.
- Claude Code: your project's `.mcp.json`.
- Zed: merge `zed.json`'s `context_servers` into Zed settings.

## Ten application integrations

| Application | Target on Windows |
| --- | --- |
| ChatGPT | Private tunnel through chatgpt mode in Setup |
| Cursor | `%USERPROFILE%/.cursor/mcp.json` |
| Claude Desktop | `%APPDATA%/Claude/claude_desktop_config.json` |
| Claude Code | Selected project's `.mcp.json` |
| Zed | `%APPDATA%/Zed/settings.json` |
| VS Code / GitHub Copilot | Selected project's `.vscode/mcp.json` |
| Codex CLI | `%USERPROFILE%/.codex/config.toml` |
| Gemini CLI | `%USERPROFILE%/.gemini/settings.json` |
| Cline in VS Code | `%APPDATA%/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json` |
| Windsurf | `%USERPROFILE%/.codeium/windsurf/mcp_config.json` |

Configuration detection means the file exists, not that the application is
installed or signed in. Custom profiles and portable installations can use
different paths: select the file shown in that application's MCP settings.
For VS Code and Claude Code, choose the project folder you actually open.
Clients and their model subscriptions/login are installed separately. The nine
local clients need only your Gemini key for this server; no OpenAI tunnel is needed.

Applying settings keeps unrelated settings and MCP servers. JSON comments and
formatting are normalized. The original bytes are saved beside the file as
`filename.insta-backup-<unique-id>`. To restore, close the client and copy the
backup over the original. Malformed settings and conflicting Insta Analyzer
entries are left untouched; review exported snippets manually for those files.
Codex uses a managed TOML block that preserves the rest of the file.

Restart/reload the client after applying. Only local Windows clients can use
these absolute Windows paths; WSL, SSH, containers and cloud agents require
their own runtime. No popularity ranking or universal compatibility is claimed.

### Verify in VS Code / GitHub Copilot

1. Save/start the runtime in Setup and wait for Ready.
2. Click **Set up AI applications**, select **VS Code / GitHub Copilot**, choose
   your project folder, and click **Apply with backup**.
3. Open that same folder in VS Code. Run **MCP: List Servers** in the Command
   Palette, select `insta-analyzer`, and start it. Accept its trust prompt if
   shown. The server output view shows startup errors.
4. Open Copilot Chat in Agent mode (or the current tool-enabled equivalent).
   Enable Insta Analyzer in the tool picker. Ask: "Use Insta Analyzer
   get_system_stats and show the result."
5. Ask: "Use Insta Analyzer to analyze this public Instagram Reel: <URL>.
   Poll the job until complete and summarize the result." Approve tool calls
   when prompted. Record the job ID/result or error for verification.

Organizational policy may disable MCP or tool use. See the
[VS Code MCP reference](https://code.visualstudio.com/docs/agents/reference/mcp-configuration).

### Verification status

All nine local adapters have automated tests for parsing, merging, backup,
repeat installation, conflict protection, real stdio MCP initialization,
five-tool discovery, and a tool call to a controlled HTTP backend. Tests read
the generated client-specific configuration; they do not run the client programs.
**Check MCP + backend** in the setup window performs the same independent
connectivity check against your running backend. It is explicitly labeled
separately from testing inside the selected application.

ChatGPT's tunnel and real Instagram analysis were verified on the maintainer's
machine. The maintainer also confirmed a successful stats call and full Instagram
analysis inside VS Code / GitHub Copilot. Real analysis inside Cursor, Claude
Desktop, Claude Code, Zed, Codex CLI, Gemini CLI, Cline and Windsurf remains
**not tested**. These are manual reports, not automated tests of those applications.

For scripting, run `python windows/clients.py list`, `export`, or `check` in the
project environment. Installation requires an explicit client and target:
`python windows/clients.py install --client vscode --target <path-to-mcp.json>`.
Checks require the backend running and do not send a video to Gemini.
Run regression checks with `python -m pytest windows mcp-server/tests -q`.

Restart or reload the client and enable Insta Analyzer. These snippets contain
absolute paths and the local backend URL, never your API keys. Each client starts
its own stdio MCP process; the launcher keeps the shared backend running. Export
again after changing the backend port or installation directory. Other clients
must support MCP stdio and may need their own configuration format. Windows is
the supported installer platform; macOS/Linux installation is not covered here.

## After restarting Windows

Sign in normally. The backend (and tunnel in ChatGPT mode) starts in the background and reconnect.
Open ChatGPT, enable Insta Analyzer, and paste a public Instagram Reel URL.
There are no terminals to launch or keys to enter on each restart. The computer
must be awake, signed in, and online for local analysis to work.

## Controls

- `windows/Settings.cmd`: update credentials, view readiness, or toggle startup.
- `windows/Start.cmd`: start the background services manually.
- `windows/Stop.cmd`: stop only the services this launcher owns.
- `windows/Disable-Autostart.cmd`: remove its Windows login entry; settings remain.
- Local logs and encrypted settings are under ignored `.insta-analyzer/`.

Moving the extracted folder requires rerunning Settings and Save so the login
entry points to the new location. To uninstall, stop the runtime, disable
autostart, then remove the installation folder yourself. Disabling startup does
not revoke keys; revoke them in their providers if you no longer need them.

## Credentials and privacy

The form masks keys. Windows DPAPI encrypts saved keys for the current Windows
user. The encrypted file is not portable to other users or computers and is
excluded from Git/release packages. Decrypted keys are passed only through child
process environments, never command-line arguments or plugin manifests.
Processes running as your Windows user can still access your local credentials.
Backend/tunnel output is redacted and rotated. Existing `.env` files are not modified.

Video files are retrieved through Instaloader and sent to Google's Gemini API for
analysis. Local downloads, results, logs, and SQLite databases remain private and
are excluded from release archives. Your Gemini/OpenAI account terms and usage
charges apply. Some Instagram posts require login or may be rate limited.

## Distribution

Each person supplies their own Gemini key. ChatGPT users also create their own
private tunnel and ChatGPT connection once. Local IDE users need neither. Sharing this source does not share the maintainer's
plugin, credentials, tunnel, or analysis history. Public OpenAI Plugin Directory
submission is separate; local-MCP submissions currently require approved-partner
eligibility. The GitHub source installer does not claim directory approval.

For maintainers, `scripts/build_release.py` creates a source ZIP from an explicit
allowlist. It excludes private files and checks for known local credentials.
Keep the upstream MIT LICENSE with any redistribution.

## Public videos from five platforms

The existing `analyze_instagram_video` tool accepts public HTTPS video links from
Instagram, Facebook (including share/r and fb.watch), TikTok, LinkedIn and X/Twitter.
The tool name and backend `instagram_url` field remain for existing clients and
job history. Ask Insta Analyzer to analyze the link, then poll `get_job_status`.
Reconnect your AI client to refresh tool descriptions.

Instagram keeps its Instaloader path. Other sites use pinned yt-dlp in a separate
process, selecting one video with combined audio/video without requiring FFmpeg.
Live streams, playlists, private content and login-only videos are outside this
feature. Browser cookies and account credentials are not imported. Some videos
require login or are blocked by the site and return an error. Extractor availability
is not proof of a successful real download on each platform.

Existing size, concurrency, storage and submission limits remain. Social downloads
have a process deadline including extraction and size checks during transfer.
Failed partial files are removed. Download workers block non-public IP connections
and do not receive provider credentials in their environment.

Verification: automated checks cover Windows adapters and MCP/backend
regressions, including URL rejection, five-platform job flow, process deadline,
size cleanup, and credential-free worker environments. The latest backend/MCP
regression run passed 52 tests. Real Facebook, LinkedIn (including lnkd.in short
links), and X videos completed download and Gemini analysis through the secure
MCP tunnel. TikTok has not yet been verified with a real video on this installation.
