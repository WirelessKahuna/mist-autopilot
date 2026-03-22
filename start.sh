#!/bin/sh
# Start Python backend in background
cd /app/backend
uvicorn main:app --host 127.0.0.1 --port 8000 &

# Wait for backend to be ready
echo "Waiting for backend..."
for i in $(seq 1 60); do
    if wget -q -O- http://127.0.0.1:8000/health > /dev/null 2>&1; then
        echo "Backend ready."
        break
    fi
    sleep 1
done

# Test nginx config
echo "Testing nginx config..."
nginx -t

# Start Nginx in foreground
echo "Starting nginx..."
exec nginx -g "daemon off;"
