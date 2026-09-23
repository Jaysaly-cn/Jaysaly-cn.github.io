FROM python:3.12-slim
WORKDIR /app
COPY requirements-lock.txt .
RUN pip install --no-cache-dir -r requirements-lock.txt && useradd --create-home appuser
COPY app ./app
COPY web ./web
RUN mkdir -p /app/data && chown -R appuser:appuser /app
USER appuser
EXPOSE 8766
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8766", "--no-proxy-headers"]
