FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip ca-certificates \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN python3 -m pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt

COPY app ./app

EXPOSE 8000
ENV PYTHONUNBUFFERED=1
ENV DB_DIR=/data

CMD ["python3","-m","uvicorn","app.main:app","--host","0.0.0.0","--port","8000","--workers","1"]
