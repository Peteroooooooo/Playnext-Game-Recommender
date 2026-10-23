#!/usr/bin/env bash
# Run on the server by scripts/deploy.ps1, after the code and data are unpacked in /opt/playnext:
# sync the venv (no model packages), start PostgreSQL in a container bound to 127.0.0.1, load the knowledge base
# when the database is empty, install and restart the systemd unit, then wait for /api/health.
set -euo pipefail
cd /opt/playnext
export PATH="$HOME/.local/bin:$PATH"
[ -f .env ] || { echo ".env is missing in /opt/playnext (run deploy.ps1 with -CopyEnv once)" >&2; exit 1; }
chmod 600 .env

env_get() { grep -E "^$1=" .env | head -1 | cut -d= -f2- | tr -d '\r'; }

uv sync --frozen --no-default-groups

if ! docker inspect playnext-db >/dev/null 2>&1; then
    mkdir -p .cache
    umask 077
    printf 'POSTGRES_DB=%s\nPOSTGRES_USER=%s\nPOSTGRES_PASSWORD=%s\n' \
        "$(env_get PGDATABASE)" "$(env_get PGUSER)" "$(env_get PGPASSWORD)" > .cache/pg.env
    docker run -d --name playnext-db --restart unless-stopped --env-file .cache/pg.env \
        -p "127.0.0.1:$(port=$(env_get PGPORT); echo "${port:-5432}"):5432" -v playnext-pgdata:/var/lib/postgresql/data \
        --health-cmd 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"' --health-interval 5s \
        postgres:16.15-alpine >/dev/null
    rm -f .cache/pg.env
fi
for _ in $(seq 60); do
    [ "$(docker inspect -f '{{.State.Health.Status}}' playnext-db)" = healthy ] && break
    sleep 2
done
[ "$(docker inspect -f '{{.State.Health.Status}}' playnext-db)" = healthy ] || { echo "database not healthy" >&2; exit 1; }

games=$(docker exec playnext-db psql -U "$(env_get PGUSER)" -d "$(env_get PGDATABASE)" -tAc \
    "select count(*) from game" 2>/dev/null || echo 0)
if [ "${games:-0}" = 0 ]; then
    echo "loading the knowledge base into PostgreSQL..."
    .venv/bin/python scripts/load_postgres.py
fi

tr -d '\r' < scripts/deploy/playnext.service > /etc/systemd/system/playnext.service
chmod 644 /etc/systemd/system/playnext.service
systemctl daemon-reload
systemctl enable playnext.service >/dev/null 2>&1
systemctl restart playnext.service
for _ in $(seq 60); do
    if out=$(curl -sf -m 30 http://10.10.10.30:8000/api/health); then echo "$out"; exit 0; fi
    sleep 2
done
echo "service did not answer /api/health; see: journalctl -u playnext -n 50" >&2
exit 1
