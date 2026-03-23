#!/bin/sh
PORT=${PORT:-8080}

echo "PORT is ${PORT}"

# Write nginx config with correct port at runtime
cat > /etc/nginx/nginx.conf << NGINXCONF
events {
    worker_connections 1024;
}
http {
    include       /etc/nginx/mime.types;
    default_type  application/octet-stream;
    sendfile      on;
    server {
        listen ${PORT};
        server_name _;
        root /usr/share/nginx/html;
        index index.html;
        location /api/ {
            proxy_pass http://127.0.0.1:8000;
            proxy_set_header Host \$host;
            proxy_set_header X-Real-IP \$remote_addr;
            proxy_read_timeout 120s;
        }
        location /health {
            access_log off;
            return 200 'ok';
            add_header Content-Type text/plain;
        }
        location / {
            try_files \$uri \$uri/ /index.html;
        }
    }
}
NGINXCONF

# Kill any existing nginx
nginx -s stop 2>/dev/null || true
sleep 1

# Start nginx in background first
echo "Starting nginx on port ${PORT}..."
nginx -g "daemon off;" &

# Start uvicorn in foreground
cd /app/backend
echo "Starting uvicorn..."
exec uvicorn main:app --host 127.0.0.1 --port 8000
