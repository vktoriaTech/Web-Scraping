FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy
WORKDIR /app
RUN apt-get update && apt-get install -y libpoppler-cpp-dev && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir --prefer-binary -r requirements.txt
RUN playwright install chromium
COPY . .
CMD ["python", "main.py"]
