FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080
WORKDIR /app
COPY mahjong_legend/ /app/mahjong_legend/
COPY web/ /app/web/
EXPOSE 8080
CMD ["python", "-m", "mahjong_legend", "--public"]
