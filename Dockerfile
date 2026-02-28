# Finger Bending Analysis Tool — Railway/Docker
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Expose port (Railway sets PORT env var)
EXPOSE 8501

# Run Streamlit (PORT set by Railway; fallback 8501 for local)
CMD ["sh", "-c", "streamlit run app.py --server.address 0.0.0.0 --server.port ${PORT:-8501} --server.fileWatcherType none --browser.gatherUsageStats false --server.headless=true"]
