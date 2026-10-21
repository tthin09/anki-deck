FROM node:22-alpine AS frontend
WORKDIR /web
COPY web/package*.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir fastapi uvicorn genanki==0.13.1 'setuptools<81' openpyxl==3.1.5
COPY src/anki_deck.py src/web_app.py /app/src/
COPY src/prompt/ /app/src/prompt/
COPY src/template/ /app/src/template/
COPY --from=frontend /web/dist /app/web/dist
RUN mkdir -p /data && chown 10001:10001 /data
ENV ANKI_DATA_DIR=/data PYTHONUNBUFFERED=1
USER 10001:10001
EXPOSE 12000
CMD ["uvicorn", "web_app:app", "--app-dir", "src", "--host", "0.0.0.0", "--port", "12000", "--workers", "1"]
