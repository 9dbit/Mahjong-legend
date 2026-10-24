FROM python:3.12-slim AS artwork
WORKDIR /app
RUN pip install --no-cache-dir 'Pillow>=10,<13'
COPY web/ /app/web/
COPY tools/build_locked_ui.py /app/tools/build_locked_ui.py
COPY tools/build_presentation_fx.py /app/tools/build_presentation_fx.py
RUN python tools/build_locked_ui.py && python tools/build_presentation_fx.py

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080
WORKDIR /app
COPY mahjong_legend/ /app/mahjong_legend/
COPY --from=artwork /app/web/ /app/web/
EXPOSE 8080
CMD ["python", "-m", "mahjong_legend", "--public"]
