FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app app
COPY web web
RUN useradd --create-home appuser && mkdir data && chown appuser data
USER appuser
EXPOSE 8769
CMD ["python","-m","uvicorn","app.main:app","--host","0.0.0.0","--port","8769"]
