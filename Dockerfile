FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 DEBUG=false DEMO_MODE=false
WORKDIR /app
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY . .
RUN useradd --create-home athar && mkdir -p /app/media /app/staticfiles && chown -R athar:athar /app
USER athar
EXPOSE 8000
CMD ["python", "deploy/serve.py"]
