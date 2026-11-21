FROM python:3.12-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df AS dependencies

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv PATH="/opt/venv/bin:$PATH"

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv==0.13.6 \
    && useradd --create-home --uid 10001 findash \
    && install -d -o findash -g findash /var/lib/findash/beat

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project

FROM dependencies AS development
COPY manage.py ./
COPY backend/ backend/
COPY api/ api/
USER findash
EXPOSE 8000
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]

FROM development AS production
USER root
RUN DJANGO_ENV=development DJANGO_BUILD_STATIC=true python manage.py collectstatic --noinput
USER findash
ENV DJANGO_ENV=production
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request as http; host = os.getenv('DJANGO_ALLOWED_HOSTS', 'localhost').split(',')[0].strip().lstrip('.'); http.urlopen(http.Request('http://127.0.0.1:8000/healthz/', headers={'Host': host}), timeout=4).close()"]
CMD ["gunicorn", "backend.wsgi:application", "--bind=0.0.0.0:8000", "--worker-tmp-dir=/dev/shm", "--timeout=120", "--access-logfile=-", "--access-logformat=%(m)s %(U)s %(s)s %(D)s"]
