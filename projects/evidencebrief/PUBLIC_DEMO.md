# Temporary public sandbox

Run `python -m uvicorn app.demo:app --host 127.0.0.1 --port 8790` with one worker.
Set `EB_DEMO_HOST` to the exact public hostname, `EB_MODEL_BASE_URL` to your local model endpoint and `EB_MODEL` to its alias. The demo uses request-scoped SQLite databases and never opens the private workspace database.

Use the official cloudflared client to run `cloudflared tunnel --no-autoupdate --url http://127.0.0.1:8790 --protocol http2`. Quick Tunnel assigns a temporary URL; set its hostname and restart the sandbox when it changes. Stop either process with Ctrl+C. Never forward the private workspace port.

## Boundaries

- Each visitor receives a random HttpOnly, SameSite=Strict cookie and a separate synthetic SQLite database. HTTPS sets Secure.
- Sessions expire after 30 minutes. Cleanup runs every 20 seconds and on requests, deferring active requests. Shutdown cleans idle databases. Crash leftovers matching the dedicated filename pattern are removed after 35 minutes once the app runs again.
- Maximum 12 sessions, 30 new sessions/hour, 60 writes/session, 40 KB/request, 3 model calls/session, 24 model calls/hour. This is a small demonstration, not production capacity or complete abuse protection.
- External URL collection and API docs are disabled. Manual sources, extraction, review, comparison and report snapshots remain functional.
- Use synthetic data only. Local model outputs require review.
- The development computer and tunnel must remain online. The URL and availability are not guaranteed. Stable cloud hosting remains unfinished.

## Verification

2026-09-23: 41 automated tests passed, including visitor isolation, forged cookies, expiry cleanup, cross-origin writes, body limits and model quotas. Public HTTPS returned 200 and a Secure cookie.

Official tunnel documentation: https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/
