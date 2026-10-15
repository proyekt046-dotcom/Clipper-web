FROM python:3.11-slim

# ffmpeg untuk proses video, curl/gnupg untuk pasang Node.js
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg curl ca-certificates gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=5000
EXPOSE 5000

# -w 1: satu proses (job berjalan di thread background di dalamnya)
# --timeout 600: beri waktu panjang untuk proses render video
CMD gunicorn -w 1 --threads 8 --timeout 600 -b 0.0.0.0:$PORT app:app
