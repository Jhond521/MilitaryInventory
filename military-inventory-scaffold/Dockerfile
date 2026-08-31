FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies first for better layer caching.
COPY pyproject.toml ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir \
        "django>=5.2,<6.0" "psycopg[binary]>=3.2" "dj-database-url>=2.2" \
        "python-dotenv>=1.0" "gunicorn>=23.0" "whitenoise>=6.7" "openpyxl>=3.1"

COPY . .

RUN python manage.py collectstatic --noinput || true

EXPOSE 8000

# Run migrations then start gunicorn.
CMD sh -c "python manage.py migrate --noinput && \
    gunicorn config.wsgi:application --bind 0.0.0.0:${PORT:-8000}"
