FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY . /app
RUN chmod +x /app/scripts/*.sh

ENTRYPOINT ["/app/scripts/web-entrypoint.sh"]
CMD ["/app/scripts/start-dev.sh"]
