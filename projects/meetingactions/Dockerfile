FROM python:3.12-slim
WORKDIR /app
COPY requirements-lock.txt .
RUN pip install --no-cache-dir -r requirements-lock.txt
COPY app ./app
COPY web ./web
RUN useradd --create-home app && mkdir data && chown app:app data
USER app
EXPOSE 8768
CMD ["python","-m","uvicorn","app.main:app","--host","0.0.0.0","--port","8768"]
