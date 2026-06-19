FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY app.py .
COPY config/ ./config/
COPY data/ ./data/
COPY demo_assets/ ./demo_assets/

EXPOSE 8501 8000
