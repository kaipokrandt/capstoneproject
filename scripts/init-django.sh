#!/usr/bin/env sh
set -eu

PROJECT_NAME="${1:-config}"

if [ -f /app/manage.py ] || [ -f manage.py ]; then
  echo "manage.py already exists. Skipping django-admin startproject."
  exit 0
fi

django-admin startproject "$PROJECT_NAME" .
echo "Created Django project '$PROJECT_NAME' in /app"
