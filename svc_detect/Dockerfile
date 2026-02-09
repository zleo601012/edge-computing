FROM python:3.12-slim

# 安装 Python3.13 + pip（容器内）
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip ca-certificates \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN python3 -m pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt

COPY app ./app

ENV PYTHONUNBUFFERED=1
ENV DB_DIR=/data
EXPOSE 8001

CMD ["python3", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "1"]
