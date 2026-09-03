FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py init_db.py ./
RUN mkdir -p /app/data && chown -R appuser:appgroup /app
USER appuser
EXPOSE 5402
CMD ["python", "app.py"]
