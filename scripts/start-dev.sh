#!/usr/bin/env sh
set -eu

cd "${DJANGO_DIR:-/app/wbs}"

python manage.py runserver 0.0.0.0:8000
