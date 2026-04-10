#!/usr/bin/env sh
set -eu

DB_HOST="${POSTGRES_HOST:-db}"
DB_PORT="${POSTGRES_PORT:-5432}"
DB_USER="${POSTGRES_USER:-balance}"
DB_NAME="${POSTGRES_DB:-balance}"
DJANGO_DIR="${DJANGO_DIR:-/app/wbs}"

if [ ! -f "${DJANGO_DIR}/manage.py" ]; then
  echo "Error: ${DJANGO_DIR}/manage.py not found. Create your Django project first." >&2
  exit 1
fi

cd "$DJANGO_DIR"

echo "Waiting for Postgres at ${DB_HOST}:${DB_PORT}..."
until python - "$DB_HOST" "$DB_PORT" <<'PY'
import socket
import sys

host = sys.argv[1]
port = int(sys.argv[2])

try:
    with socket.create_connection((host, port), timeout=2):
        pass
except OSError:
    raise SystemExit(1)
PY
do
  sleep 1
done

echo "Running migrations..."
python manage.py migrate --noinput

echo "Ensuring superuser exists..."
python manage.py shell <<'PY'
import os
from django.contrib.auth import get_user_model

User = get_user_model()

if User.objects.filter(is_superuser=True).exists():
    print("Superuser already exists. Skipping bootstrap.")
    raise SystemExit(0)

username = os.getenv("DJANGO_SUPERUSER_USERNAME", "").strip()
password = os.getenv("DJANGO_SUPERUSER_PASSWORD", "")
email = os.getenv("DJANGO_SUPERUSER_EMAIL", "").strip()

if not username or not password:
    print("No superuser exists, but DJANGO_SUPERUSER_USERNAME/PASSWORD are not set.")
    raise SystemExit(0)

User.objects.create_superuser(
    username=username,
    password=password,
    email=email or "",
)
print(f"Created bootstrap superuser: {username}")
PY

echo "Starting Django service..."
exec "$@"
