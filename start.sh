#!/bin/sh
cd /app/backend
uvicorn main:app --host 127.0.0.1 --port 8000 &

echo "Waiting for backend..."
for i in $(seq 1 60); do
    if wget -q -O- http://127.0.0.1:8000/health > /dev/null 2>&1; then
        echo "Backend ready."
        break
    fi
    sleep 1
done

nginx -s stop 2>/dev/null || true
sleep 1

echo "Starting nginx on port 8080..."
exec nginx -g "daemon off;"
