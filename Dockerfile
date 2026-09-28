FROM node:22-alpine AS frontend
WORKDIR /web
COPY web/package*.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir fastapi uvicorn genanki==0.13.1 openpyxl 'setuptools<81'
COPY src/anki_deck.py src/web_app.py src/agent-prompt.md src/reverse-prompt.md /app/src/
COPY --from=frontend /web/dist /app/web/dist
ENV ANKI_DATA_DIR=/data PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["uvicorn", "web_app:app", "--app-dir", "src", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
