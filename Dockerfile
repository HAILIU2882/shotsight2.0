FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install --yes --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 shotsight \
    && useradd --uid 10001 --gid shotsight --create-home shotsight

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir ".[vision]" \
    && mkdir -p /app/data \
    && chown -R shotsight:shotsight /app/data

USER shotsight
EXPOSE 4173

CMD ["uvicorn", "shotsight2.main:app", "--host", "0.0.0.0", "--port", "4173"]
