FROM python:3.11-slim

# Install browser deps (ARM + x86 friendly)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        chromium \
        chromium-driver \
        ca-certificates \
        fonts-liberation \
        libnss3 \
        libxss1 \
        libasound2 \
        libgbm1 \
        xdg-utils && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install matching chromedriver via webdriver-manager
RUN python -c "from selenium.webdriver.chrome.service import Service; from selenium import webdriver; print('selenium ok')"

COPY scraper.py .

ENV HEADLESS=true
ENV PYTHONUNBUFFERED=1

CMD ["python", "scraper.py"]
