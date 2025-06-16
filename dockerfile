# Python image
FROM python:3.10-slim

#Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

#Set working directory
WORKDIR /app

#Install system dependencies
RUN apt-get update && apt-get install -y ffmpeg curl && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Install dependencies
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Copy app files
COPY . .

# Expose port 5000
EXPOSE 5000

# Start app
CMD ["gunicorn", "app:app", "--bind","0.0.0.0:5000"]

