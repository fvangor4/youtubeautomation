FROM python:3.11-slim

# Prevents Python from writing .pyc files and buffers
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install app dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

# Copy the application code
COPY . .

EXPOSE 5000

# Use gunicorn for production-grade serving
CMD ["gunicorn", "-b", "0.0.0.0:5000", "app:app"]
