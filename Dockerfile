FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY forex_agent /app/forex_agent
COPY config /app/config
RUN groupadd -g 10001 agent && useradd -u 10001 -g agent -M agent \
    && mkdir -p /app/data && chown agent:agent /app/data
USER agent
EXPOSE 8000
CMD ["python", "-m", "forex_agent", "serve", "--host", "0.0.0.0", "--policy", "config/risk.json"]
