FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Ensure data directories exist
RUN mkdir -p /data/uploads

ENV FLASK_APP=app.py \
    DB_PATH=/data/iadroc.db \
    UPLOAD_FOLDER=/data/uploads

EXPOSE 5000

CMD ["gunicorn", "-b", "0.0.0.0:5000", "app:app"]
