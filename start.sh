#!/bin/sh
# Use Railway's PORT or default to 80
PORT=${PORT:-80}

# Write nginx config with correct port
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

# Start Python backend in background
cd /app/backend
uvicorn main:app --host 127.0.0.1 --port 8000 &

# Kill any existing nginx
nginx -s stop 2>/dev/null || true
sleep 1

echo "Starting nginx on port ${PORT}..."
exec nginx -g "daemon off;"
