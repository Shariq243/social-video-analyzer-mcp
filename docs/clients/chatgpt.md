# ChatGPT: private Social Video Analyzer connection

[Back to the main guide](../../README.md)

## Requirements

Windows 10 or 11 x64, your own Gemini key, and a ChatGPT account/workspace
with custom MCP/private tunnel access. Availability and organization policy vary.
Windows 11 was tested; Windows 10 remains a compatibility target pending a real
machine test. The computer runs the backend and must stay awake and online.

## Install and connect

1. Download the repository ZIP, extract to a permanent folder, and run **Setup.cmd**.
2. In [OpenAI Platform tunnels](https://platform.openai.com/settings/organization/tunnels),
   create your own tunnel and associate the intended ChatGPT workspace. Copy its ID.
3. Create your own runtime key whose principal has **Tunnels Read + Use**. Complete
   account login/authorization yourself. Do not use an administrator key or share keys.
4. In Setup select **chatgpt**, enter your own tunnel ID, runtime key and Gemini key,
   and click **Save and start**. Leave automatic startup checked if desired. Keys
   are encrypted for your Windows user; do not paste them in a chat or commit them.
5. Wait for **Ready**. In ChatGPT's custom MCP/app/plugin settings, add a custom
   server named **Social Video Analyzer**. Select the **Tunnel** connection option and
   your tunnel ID. Do not paste a tunnel ID into a Server URL field.
6. For this private tunnel flow, select **No authentication** in the app form:
   tunnel access is authenticated by the runtime key and workspace permissions.
   This does not make a public HTTP server unauthenticated. Install privately
   and enable Social Video Analyzer in a new conversation.
7. If Tunnel or custom MCP creation is unavailable, check workspace eligibility
   and admin policy. This installer cannot enable a restricted account feature.

## Test

Ask: "Use Social Video Analyzer get_system_stats and show the result."
Then ask: "Use Social Video Analyzer to analyze <PUBLIC_VIDEO_URL>. Poll the job
until complete and summarize its analysis." Approve tool calls as prompted.

## Restart and stop

With automatic startup enabled, sign in to Windows and wait for the services
to reconnect. Enable the app in your ChatGPT conversation. Run `windows/Stop.cmd`
to stop this installation; `windows/Disable-Autostart.cmd` disables future login
startup. Close older manually started backends/tunnels if ports conflict.

## Verification and privacy

Private tunnel connection and full Instagram analysis were verified on the
maintainer's machine. Every user creates their own connection and supplies their
own credentials. The repository does not share the maintainer's plugin or quota.
Video content is sent to Gemini for analysis. Public Instagram access can fail
due to rate limits or login requirements; provider quota/usage charges apply.
