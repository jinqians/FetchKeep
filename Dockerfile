FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates tzdata curl unzip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt \
    && python -m pip install --no-cache-dir --pre -U "yt-dlp[default,curl-cffi]" "yt-dlp-ejs" \
    && curl -fsSL https://deno.land/install.sh | sh \
    && ln -sf /root/.deno/bin/deno /usr/local/bin/deno \
    && yt-dlp --list-impersonate-targets | grep -qi "Chrome" \
    && deno --version >/dev/null \
    && python -c "import fastapi, uvicorn, multipart, yt_dlp, gallery_dl; print('Python dependencies OK')" \
    && ffmpeg -version >/dev/null

COPY app ./app
COPY static ./static
COPY templates ./templates
# 分发镜像等于分发作品，AGPL 要求随附许可证正文。
COPY LICENSE .

RUN mkdir -p /data/downloads /data/cookies

EXPOSE 9080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9080"]
