# Edge Cutover Runbook — dev server to production bundle

Moving the public edge from the Vite dev server to the built bundle served
by nginx over TLS.

**Not yet executed.** Written after an attempt on 2026-08-11 took the site
down for roughly three minutes. Every step below exists because something
in that attempt went wrong.

## What is actually changing

Only **nginx**. The backend, workers, consumers and every other service
stay exactly as they are.

Today nginx runs the stock `nginx:1.27-alpine` image with `nginx.dev.conf`
bind-mounted, terminating TLS and proxying `/` to the Vite dev server.
After cutover it runs `blinkengage-nginx:prod`, which bakes the built
bundle in and serves it directly.

This is why the backend does not need to move, and why it must not be
allowed to.

## The three traps

1. **`depends_on` drags the backend in.** `docker compose … up -d nginx`
   with the prod overlay also recreated the backend, because nginx depends
   on it. Use `--no-deps`.

2. **`blinkengage-backend:latest` is a _dev_ image.** Dev (`target: dev`)
   and prod (`target: runtime`) both resolve to the same derived tag, so
   the tag alone does not tell you which you have. Verified 2026-08-11:
   `:latest` contains `/app/tests` and `/opt/venv/bin/pytest`, which only
   the dev stage produces. Recreating the backend under the prod overlay
   therefore starts a **dev image with no bind mounts**, and it dies on
   `ChangelogFormatError`. `--no-deps` avoids this; the permanent guard is
   an explicit `image:` tag per service in the overlay, as `nginx` has.

3. **Ports 80/443 can only be held by one container.** A literal
   start-before-stop on the real ports is impossible. The substitute is to
   prove the new image completely on alternate ports _first_, so the swap
   itself is a few seconds of recreate with a known-good image.

## PRE-CHECK

Nothing here touches the running edge.

```bash
cd /root/BlinkEngage

# 1. Build the production nginx image (bakes the frontend bundle).
docker compose -f docker-compose.yml -f docker-compose.prod.yml build nginx

# 2. Confirm the bundle is a real build, not the dev server.
docker run --rm --entrypoint sh blinkengage-nginx:prod -c \
  'ls /usr/share/nginx/html/assets/*.js | head -3; grep -c "@vite/client" /usr/share/nginx/html/index.html'
#    expect: hashed asset filenames, and 0 for @vite/client

# 3. Certificates present on the host and not near expiry.
openssl x509 -enddate -noout \
  -in /etc/letsencrypt/live/engage.blinkconnected.com/fullchain.pem

# 4. Config parses inside the image.
docker run --rm --entrypoint nginx -v /etc/letsencrypt:/etc/letsencrypt:ro \
  blinkengage-nginx:prod -t

# 5. Full rehearsal on alternate ports, against the live backend.
docker run -d --name nginx-prodtest --network blinkengage \
  -p 127.0.0.1:8080:80 -p 127.0.0.1:8443:443 \
  -v /etc/letsencrypt:/etc/letsencrypt:ro \
  -v /root/BlinkEngage/docker/nginx/acme:/var/www/acme:ro \
  blinkengage-nginx:prod

curl -s -o /dev/null -w 'healthz(80) %{http_code}\n' http://127.0.0.1:8080/healthz   # 200, no redirect
curl -s -o /dev/null -w 'root(80)    %{http_code}\n' http://127.0.0.1:8080/          # 301
curl -sk --resolve engage.blinkconnected.com:8443:127.0.0.1 \
     -o /dev/null -w 'root(443)   %{http_code}\n' https://engage.blinkconnected.com:8443/
curl -sk --resolve engage.blinkconnected.com:8443:127.0.0.1 \
     -o /dev/null -w 'api(443)    %{http_code}\n' https://engage.blinkconnected.com:8443/api/v1/health
echo | openssl s_client -connect 127.0.0.1:8443 \
     -servername engage.blinkconnected.com 2>/dev/null | openssl x509 -noout -subject -issuer

docker rm -f nginx-prodtest
```

**Do not continue unless every line above is as annotated.**

Confirm the backend is healthy _before_ touching anything, so a
post-cutover failure cannot be misattributed:

```bash
docker compose ps backend
curl -s -o /dev/null -w 'live api %{http_code}\n' https://engage.blinkconnected.com/api/v1/health
```

## CUTOVER

```bash
cd /root/BlinkEngage

# --no-deps is the whole safety of this step: it recreates nginx and
# nothing else. Without it, compose recreates the backend under the prod
# overlay and the site goes down.
docker compose -f docker-compose.yml -f docker-compose.prod.yml \
  up -d --no-deps nginx
```

Immediately after:

```bash
docker compose ps nginx
curl -s -o /dev/null -w 'https root     %{http_code}\n' https://engage.blinkconnected.com/
curl -s -o /dev/null -w 'https api      %{http_code}\n' https://engage.blinkconnected.com/api/v1/health
curl -s -o /dev/null -w 'http  redirect %{http_code}\n' http://engage.blinkconnected.com/
curl -s https://engage.blinkconnected.com/ | grep -c '@vite/client'   # expect 0
```

Expected: `200`, `200`, `301`, `0`. Then confirm nothing else moved:

```bash
docker compose ps --format '{{.Service}} {{.State}}' | grep -v running   # expect empty
curl -s http://localhost:9090/api/v1/targets | grep -c '"health":"up"'   # expect 12
```

## ROLLBACK

Trigger on any of: HTTPS not 200, API not 200, certificate error, or nginx
not reaching `running` within ~30 seconds.

```bash
cd /root/BlinkEngage

# Restores the stock image with nginx.dev.conf bind-mounted — the exact
# edge that was running before. Base compose only: no prod overlay.
docker compose up -d --no-deps nginx

curl -s -o /dev/null -w 'https root %{http_code}\n' https://engage.blinkconnected.com/
curl -s -o /dev/null -w 'https api  %{http_code}\n' https://engage.blinkconnected.com/api/v1/health
docker compose ps nginx
```

If the backend was disturbed despite `--no-deps`:

```bash
docker compose up -d --no-deps backend     # base compose: restores the bind mounts
docker compose ps backend                  # wait for (healthy)
```

Recovery on 2026-08-11 took under a minute by this route: backend healthy
in 19 seconds, nginx immediately after.

## After a successful cutover

The Vite dev container is no longer serving anything but is still running
under the base compose. It is excluded from the prod overlay by
`profiles: ["dev-only"]`. Stop it only once the new edge has been stable:

```bash
docker compose stop frontend
```

Then confirm the site still serves. If it stops working at this point, the
edge was still proxying to the dev server and the cutover did not take.
