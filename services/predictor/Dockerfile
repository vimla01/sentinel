FROM python:3.11-slim

WORKDIR /app
COPY services/predictor/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
COPY services/__init__.py services/__init__.py
COPY services/predictor/ services/predictor/

EXPOSE 8080
USER 10001
CMD ["python", "-m", "uvicorn", "services.predictor.main:app", "--host", "0.0.0.0", "--port", "8080"]
