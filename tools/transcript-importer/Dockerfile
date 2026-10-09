# Transcript importer: watches a folder (e.g. a TrueNAS share) for call transcripts and
# imports their action items into Plane. Standard library only.
FROM python:3.12-alpine

RUN adduser -D -u 1000 importer && mkdir -p /data /transcripts && chown importer /data
WORKDIR /app
COPY transcript_importer ./transcript_importer

USER importer
ENV PYTHONUNBUFFERED=1 \
    TRANSCRIPT_DIR=/transcripts \
    TRANSCRIPT_STATE_FILE=/data/transcript-importer-state.json
VOLUME ["/data"]
ENTRYPOINT ["python", "-m", "transcript_importer"]
CMD ["watch"]
