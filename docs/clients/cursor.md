# Cursor: Social Video Analyzer setup

[Back to the main guide](../../README.md)

## Requirements

Windows 10 or 11 x64; this application installed and signed in with access to
tool use/MCP; your own Google Gemini API key. This installer targets local
Windows applications, not WSL, SSH, containers or cloud agents. The application's
own current system requirements still apply. Windows 11 was tested; Windows 10
is a compatibility target and has not been tested on a real machine here.

## Install and connect

1. Download this repository using Code > Download ZIP. Extract it into a permanent
   folder you own and run **Setup.cmd**. Keep the entire extracted project together.
2. Choose **local** mode, enter **your own Gemini API key**, and click **Save and
   start**. Keep automatic startup enabled if you want the backend after login.
   No OpenAI tunnel or OpenAI API key is needed for this client. If the default
   backend port 18002 is occupied by another installation, choose another port,
   such as 18003, and export/apply the configuration again.
3. Wait for **Ready**, then click **Set up AI applications (10 clients)**.
4. Select **Cursor**. Choose the configuration file/project and click **Apply
   with backup**. Expected target: `%USERPROFILE%/.cursor/mcp.json`. Configuration section: `mcpServers`.
   Custom profiles and portable installs can use another path; use the application's
   MCP settings to find it. The installer backs up existing files and preserves
   unrelated settings. JSON comments/formatting are normalized. Conflicting
   Social Video Analyzer entries are not overwritten automatically.
5. Restart Cursor, open its MCP settings (search Settings for MCP), and enable `insta-analyzer`. Open Agent chat and enable its tools.

## Test in the application

First ask:

> Use Social Video Analyzer get_system_stats and show the result.

Then supply a public Instagram Reel or post URL:

> Use Social Video Analyzer to analyze this URL: <PUBLIC_VIDEO_URL>. Poll the job until it completes, then summarize the analysis.

Approve tool calls as prompted. A job ID means processing started; poll
`get_job_status` to obtain the result. Instagram can rate limit or require login;
Gemini failures can arise from an invalid key, quota or model availability.

## Troubleshooting and stopping

- No tools: confirm the selected configuration location, restart the application,
  and check its MCP output/status. Trust and organization policy can block tools.
- Backend error: open Social Video Analyzer Settings and wait for Ready. **Check MCP +
  backend** independently checks the server, not the application's own connection.
- Existing configuration conflict: export the matching snippet from Setup and
  review it manually. To restore, close the client and copy its adjacent
  `.insta-backup-<id>` file over the original settings file.
- Run `windows/Stop.cmd` to stop this installation's runtime. Disable autostart
  separately if desired. Keep the computer awake and online while analyzing.

## Verification

Automated configuration/protocol tests passed; real analysis inside this application has not yet been verified.

Generated configuration tests initialize real stdio MCP, discover five tools,
and call a controlled backend. Each person supplies their own key; the shared
repository and client configurations contain no maintainer credentials.

[Official client documentation](https://cursor.com/docs/mcp)
