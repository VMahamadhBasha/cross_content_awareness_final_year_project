FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 ffmpeg && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./
COPY requirements-ml.txt ./
ARG INSTALL_ML=false
RUN pip install -r requirements.txt && if [ "$INSTALL_ML" = "true" ]; then pip install -r requirements-ml.txt; else pip install langgraph; fi
COPY . .
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
