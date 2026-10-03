# WohnWerk machine handoff — wohnwerk.lainlounge.org

Persistent host/runtime recovery notes for future ChatGPT infrastructure sessions. This file is outside the WohnWerk Git repository.

## Update rule
Update only when ChatGPT itself installs software or materially changes this host/runtime. Never store secrets, passwords, DB URLs, relay secrets, private keys, API keys, proxy credentials, or capability tokens here.

## Host and access
- Debian GNU/Linux 13 (trixie), observed 13.6.
- Sentinel execution: sentinel-ai uid/gid 1001, home /home/sentinel-ai, shell /bin/sh.
- sentinel-ai has no general sudo. Root production changes use the normal temporary operator bootstrap through Tethys Sentinel; remove temporary bootstrap after privileged deployment work when applicable.

## Persistent layout
- Production checkout: /opt/wohnwerk (root-owned).
- WohnWerk venv: /opt/wohnwerk/.venv.
- WohnWerk runtime env: /opt/wohnwerk/.env (sensitive; never print/copy into chat, GitHub or logs).
- Persistent WohnWerk state: /var/lib/wohnwerk.
- Machine handoff: /home/sentinel-ai/WohnWerk_MACHINE_HANDOFF.md.
- Read-only Git inspection: git -c safe.directory=/opt/wohnwerk -C /opt/wohnwerk ... ; do not persist a global safe.directory exception.

## WohnWerk runtime
- /etc/systemd/system/wohnwerk.service runs as www-data:www-data, WorkingDirectory=/opt/wohnwerk.
- Exec: /opt/wohnwerk/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --proxy-headers --forwarded-allow-ips=127.0.0.1
- EnvironmentFile=/opt/wohnwerk/.env.
- Caddy is the public reverse proxy. Local health: http://127.0.0.1:8000/health.
- Core units: wohnwerk.service, wohnwerk-refresh.timer, wohnwerk-images.timer, wohnwerk-liveness.timer, caddy.
- Remote HA PostgreSQL/PostGIS is configured through /opt/wohnwerk/.env; never expose the connection string.
- /usr/bin/psql is pg_wrapper. Alembic/app tools are in /opt/wohnwerk/.venv.

## Verified tools / caveats
- /usr/bin/python3 (Python 3.13), /usr/bin/git, /usr/bin/curl, /usr/bin/caddy, /usr/bin/psql and /usr/bin/Xvfb are present.
- Do not assume /usr/bin/chromium; browser-backed acquisition uses managed Chromium.
- /tmp is a small tmpfs (~2 GiB); use /var/tmp for large staging.
- Deploy only an exact validated release SHA; require exact-release CI and validate outside /opt/wohnwerk before cutover.

## Captcha solver sidecar
- Installed separately from WohnWerk at /opt/captcha-solver-global.
- Upstream repository: 0xMissy22/captcha-solver-global, pinned commit d415fd7151e61a1cec677076036834fc178545c1.
- Dedicated unprivileged account: captcha-solver; writable state/home: /var/lib/captcha-solver.
- Dedicated venv: /opt/captcha-solver-global/venv.
- Systemd unit: /etc/systemd/system/captcha-solver.service.
- The service runs headed CloakBrowser paths inside Xvfb on this headless VM; no physical display is required.
- Listener is localhost-only: http://127.0.0.1:8877. No Caddy/public exposure was configured.
- SOLVER_ALLOW_PRIVATE is intentionally unset. No proxy, residential/mobile routing, Mistral/API keys or public bearer layer were configured.
- The sidecar is installed but is NOT automatically wired into Immowelt, ImmoScout24, RE/MAX, VON POLL or any WohnWerk source.
- Upstream README suggests python server.py, but pinned server.py has no __main__ launcher. The service therefore runs uvicorn server:app --host 127.0.0.1 --port 8877 --loop asyncio.
- CloakBrowser binary/cache lives under the captcha-solver service user's state/home and may be pre-downloaded with: sudo -u captcha-solver env HOME=/var/lib/captcha-solver /opt/captcha-solver-global/venv/bin/python -m cloakbrowser install.
- Health check: curl -fsS http://127.0.0.1:8877/health.
- Stop/disable: systemctl disable --now captcha-solver.service. Full uninstall additionally removes /etc/systemd/system/captcha-solver.service, /opt/captcha-solver-global and /var/lib/captcha-solver, then daemon-reload; remove the service account only after confirming nothing else uses it.
- Qwen3.6-35B-A3B is a viable multimodal backend through an OpenAI-compatible vision endpoint, but upstream common/mistral.py is hard-wired to api.mistral.ai and common/apikey.txt. Qwen is therefore NOT wired yet; integration requires a small backend adapter and the existing Qwen inference endpoint/model identifier.

## Current checkpoint
- WohnWerk production target for this maintenance is v0.4.15 exact SHA abdec02fee6e0f984d9f298d6b7e7ef8879dea87, with no DB migration/dependency changes from v0.4.14.
- Previous accepted rollback point: v0.4.14 exact SHA bc223ff2aa17306528300d4d3e31ad4180ca19fa.
- v0.4.15 hardens the German source model: VON POLL is manual-only after production HTTP 403 and unstable URL-hash identities cannot grant reconciliation/disappearance authority.
- For product decisions and detailed release history, read repository HANDOFF.md.
