FROM python:3.11-slim

WORKDIR /app
COPY services/diagnosis_agent/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
COPY services/__init__.py services/__init__.py
COPY services/diagnosis_agent/ services/diagnosis_agent/
COPY runbooks/ runbooks/

EXPOSE 8080
USER 10001
CMD ["python", "-m", "uvicorn", "services.diagnosis_agent.main:app", "--host", "0.0.0.0", "--port", "8080"]
