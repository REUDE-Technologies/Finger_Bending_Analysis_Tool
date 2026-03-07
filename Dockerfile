# Finger Bending Analysis Tool — Railway/Docker
# Uses PyTorch CPU-only to keep image under Railway 4GB limit.
FROM python:3.11-slim

WORKDIR /app

# Install dependencies (torch omitted here; installed as CPU-only below)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# PyTorch CPU-only (~1GB vs ~8GB with CUDA) so image stays under 4GB
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# Copy application
COPY . .

# Entrypoint uses PORT from Railway (set PORT=8501 in Railway Variables)
RUN chmod +x entrypoint.sh

EXPOSE 8501

ENTRYPOINT ["/bin/sh", "./entrypoint.sh"]
