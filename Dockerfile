FROM python:3.13-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY backend/pyproject.toml backend/
RUN pip install --no-cache-dir \
    fastapi uvicorn pydantic pydantic-settings sqlalchemy psycopg2-binary \
    alembic "celery[redis]" redis python-multipart aiofiles \
    "python-jose[cryptography]" "passlib[bcrypt]" "bcrypt>=4.0.0,<4.1.0" \
    python-dotenv langchain-openai langchain-core langchain-groq groq faiss-cpu numpy pillow \
    pytesseract httpx pytest pytest-asyncio pytest-cov

COPY backend/ /app/

RUN mkdir -p /app/storage /app/faiss_index

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
