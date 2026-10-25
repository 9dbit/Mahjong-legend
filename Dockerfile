FROM node:24-bookworm-slim AS studio
WORKDIR /app/studio_ui
COPY studio_ui/package*.json ./
RUN npm ci
COPY studio_ui/ ./
RUN npm run build

FROM python:3.12-slim AS artwork
WORKDIR /app
RUN pip install --no-cache-dir 'Pillow==12.3.0'
COPY web/ /app/web/
COPY mahjong_legend/ /app/mahjong_legend/
COPY tools/ /app/tools/
RUN python tools/build_locked_ui.py && python tools/build_presentation_fx.py && python tools/build_approved_ui.py && python tools/build_portrait_ui.py && python tools/build_responsive_runtime.py --runtime-only && python tools/build_fullframe_ui.py --runtime-only && python tools/build_ornament_v094.py && python tools/build_studio_runtime.py

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY --from=artwork /app/mahjong_legend/ /app/mahjong_legend/
COPY --from=artwork /app/web/ /app/web/
COPY --from=studio /app/web/studio/ /app/web/studio/
COPY studio_server/ /app/studio_server/
COPY game_studio/ /app/game_studio/
COPY manage.py /app/manage.py
COPY tools/start_studio.py /app/tools/start_studio.py
EXPOSE 8080
CMD ["python", "tools/start_studio.py"]
