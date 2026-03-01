#!/bin/sh
# Use PORT from Railway (or 8501 for local Docker)
PORT=${PORT:-8501}
echo "Starting Streamlit on 0.0.0.0:${PORT}"
exec streamlit run app.py \
  --server.address 0.0.0.0 \
  --server.port "$PORT" \
  --server.fileWatcherType none \
  --browser.gatherUsageStats false \
  --server.headless=true
