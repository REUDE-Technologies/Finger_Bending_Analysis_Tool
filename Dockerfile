# Finger Bending Analysis Tool — Railway/Docker
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Entrypoint uses PORT from Railway (set PORT=8501 in Railway Variables)
RUN chmod +x entrypoint.sh

EXPOSE 8501

ENTRYPOINT ["/bin/sh", "./entrypoint.sh"]
