FROM python:3.12-alpine

# Non-root user for the service
RUN addgroup -S app && adduser -S app -G app

WORKDIR /srv

COPY app.py .

RUN chown -R app:app /srv
USER app

ENV PORT=8085
EXPOSE 8085

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8085/api', timeout=3)" || exit 1

CMD ["python", "-u", "app.py"]
