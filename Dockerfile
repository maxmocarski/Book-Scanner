FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py scanning.py schema.py ./
RUN useradd --system --uid 10001 bookbridge && mkdir /data && chown bookbridge /data
USER bookbridge
ENV BOOKBRIDGE_DATA=/data
EXPOSE 8503
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8503"]
