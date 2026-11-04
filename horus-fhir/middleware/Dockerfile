FROM python:3.12-slim AS runtime
RUN useradd --uid 10003 --no-create-home --shell /usr/sbin/nologin fhirapi
WORKDIR /srv
COPY requirements.lock .
RUN pip install --no-cache-dir --no-deps -r requirements.lock
COPY app ./app
COPY config ./config
USER 10003:10003
EXPOSE 8000
HEALTHCHECK --interval=5s --timeout=3s --retries=20 CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"]
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]

# fhir-api:0.1.0-test = runtime + pytest + tests (docker build --target test)
FROM runtime AS test
USER root
COPY requirements-dev.lock .
RUN pip install --no-cache-dir --no-deps -r requirements-dev.lock
COPY tests ./tests
USER 10003:10003
CMD ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"]

# Default target: the runtime image, without tests or pytest.
FROM runtime
