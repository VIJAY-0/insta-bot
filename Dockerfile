FROM python:3.12-slim

# ffmpeg lets yt-dlp merge the best video and audio streams into one MP4.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg \
 && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY reelbot ./reelbot

RUN useradd --create-home --uid 1000 app && mkdir downloads && chown app downloads
USER app

# Settings come from the environment (docker compose passes .env); accounts.toml and
# downloads/ are mounted from the host. See docker-compose.yml.
EXPOSE 5000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s \
  CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/' % os.getenv('PORT', '5000'), timeout=4)"
CMD ["python", "-m", "reelbot"]
