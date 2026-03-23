#!/bin/sh
# Start nginx first so healthcheck passes immediately
nginx -s stop 2>/dev/null || true
sleep 1
nginx -g "daemon off;" &

# Then start uvicorn
cd /app/backend
echo "Starting uvicorn..."
exec uvicorn main:app --host 127.0.0.1 --port 8000
