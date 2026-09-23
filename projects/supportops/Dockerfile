FROM python:3.12-slim
WORKDIR /app
COPY requirements-lock.txt .
RUN pip install --no-cache-dir -r requirements-lock.txt && useradd --create-home appuser
COPY app ./app
COPY web ./web
COPY examples ./examples
RUN mkdir -p /app/data && chown -R appuser:appuser /app
USER appuser
EXPOSE 8765
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8765", "--no-proxy-headers"]
