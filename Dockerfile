FROM python:3.12-slim AS artwork
WORKDIR /app
RUN pip install --no-cache-dir 'Pillow>=10,<13'
COPY web/ /app/web/
COPY mahjong_legend/ /app/mahjong_legend/
COPY tools/ /app/tools/
RUN python tools/build_locked_ui.py && python tools/build_presentation_fx.py && python tools/build_approved_ui.py && python tools/build_portrait_ui.py && python tools/build_responsive_runtime.py --runtime-only && python tools/build_fullframe_ui.py --runtime-only

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080
WORKDIR /app
COPY --from=artwork /app/mahjong_legend/ /app/mahjong_legend/
COPY --from=artwork /app/web/ /app/web/
EXPOSE 8080
CMD ["python", "-m", "mahjong_legend", "--public"]
