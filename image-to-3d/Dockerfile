FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml .
COPY img3d/ ./img3d/
COPY static/ ./static/

RUN pip install --no-cache-dir -e .

EXPOSE 8000

CMD ["uvicorn", "img3d.main:app", "--host", "0.0.0.0", "--port", "8000"]
