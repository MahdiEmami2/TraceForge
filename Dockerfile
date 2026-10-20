# TraceForge application image: one image, three services (command selects
# the service module).  Python 3.12-slim + pinned dependencies from
# requirements.txt.  The image runs as a non-root user.

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src
RUN useradd --create-home --shell /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /app
USER appuser

ENV PYTHONPATH=/app/src

EXPOSE 8000

# The compose file overrides ``command`` per service; this default runs the
# inventory service so ``docker run`` alone also works.
CMD ["uvicorn", "traceforge.inventory.main:create_inventory_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
