# Security and upgrading

The backend binds to loopback and requires an internal credential on every route
except `/health`. It rejects untrusted Host/Origin values. The launcher creates
the credential automatically and stores it with Windows CurrentUser DPAPI; local
MCP processes recover it from that encrypted store. Client JSON/TOML exports do
not contain provider or backend keys. Programs running as your Windows user can
still use your local credentials: this does not isolate hostile same-user software.

## Upgrade from the initial release

1. Stop the old runtime through Settings/Stop.cmd and close its MCP processes
   (restart the IDE or disconnect its tools).
2. Update the project source in its permanent installation folder, preserving
   `.insta-analyzer`, `.env` files, and local data. Do not delete saved credentials.
3. Run Setup.cmd, then Save and start. Old encrypted settings are migrated to add
   the internal backend credential. The existing Gemini key is kept.
4. Restart/reconnect your AI client. Regenerate its configuration if the project
   path or backend port changed. Test get_system_stats before analyzing a URL.

Manual deployments must set the same random `BACKEND_API_KEY` (at least 32
characters) in the backend and MCP process environments. Keep it out of commands,
Git, client manifests and logs. The backend fails closed without it. Manual HTTP
MCP deployments additionally require `MCP_API_KEYS` as before. Only expose the
authenticated MCP transport, never the backend API directly.

## Resource limits and privacy

Defaults: at most 2 concurrent analysis jobs, 5 submissions per minute, 100 MB
per downloaded/uploaded video, and a 120-second streaming download deadline.
Individual network operations can also wait for their socket timeout. New jobs
are rejected when the configured 1 GB local media/results budget cannot reserve
space for concurrent downloads. Clear old jobs to resume; this does not silently
delete your history. The budget is an admission check, not an OS filesystem quota.
Provider metadata lookups and analysis have separate SDK/network timeouts.

Limits can be set in backend environment variables: `MAX_CONCURRENT_JOBS`,
`MAX_SUBMISSIONS_PER_MINUTE`, `MAX_FILE_SIZE`, `MAX_STORAGE_BYTES`, and
`DOWNLOAD_TIMEOUT_SECONDS`. Use positive values. Rejected jobs return HTTP 429
or 507. Partial media is removed on failure; oversized media is never sent to
Gemini. Stream size is checked even when Content-Length is absent or misleading.

Backend file/console logs redact configured secrets, including exception traces.
Backend and supervisor logs rotate. Never share logs without reviewing them.
Video content is sent to Google's Gemini service for analysis; provider file
retention and usage policies apply. It is not made public by this repository.

The November 3, 2026 source/history audit found no exposed maintainer secrets
and no known OSV advisories for the installed package versions. Regression tests
cover the authentication boundary, redaction, size limits and admission controls;
they are not a guarantee against all vulnerabilities. Windows 10 still needs a
real-machine test. Do not post credentials, private videos or sensitive logs in
public issues; redact them before submitting a bug report.
