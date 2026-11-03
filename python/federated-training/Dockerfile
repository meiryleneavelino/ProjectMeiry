FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 OPENBLAS_NUM_THREADS=1
WORKDIR /app
COPY python/federated-training/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid 10001 --create-home trainer
COPY proto-files /proto
RUN mkdir /app/proto && python -m grpc_tools.protoc -I/proto --python_out=/app/proto --grpc_python_out=/app/proto /proto/*.proto
ENV PYTHONPATH=/app/proto
COPY python/federated-training/model.py python/federated-training/service.py python/federated-training/integration.py ./
USER 10001
ENTRYPOINT ["python", "service.py"]
CMD ["serve"]