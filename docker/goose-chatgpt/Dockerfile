# Independent diagnostic image: no Labcat package, Codex helper or host data.
FROM python:3.13-slim@sha256:9d2e5553305c7c7b0097999bb17187c69b921ccd6bc9d40e4bb5ebe652c00285 AS binary
ARG TARGETARCH
WORKDIR /build
COPY scripts/install_goose.py ./
RUN python -c 'import sys; from pathlib import Path; from install_goose import install; install("goose", sys.argv[1], Path("/agent-bin"))' "$TARGETARCH"

FROM python:3.13-slim@sha256:9d2e5553305c7c7b0097999bb17187c69b921ccd6bc9d40e4bb5ebe652c00285
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY --from=binary /agent-bin/goose /usr/local/bin/goose
COPY scripts/goose_chatgpt_standalone.py /opt/probe.py
COPY third_party/GOOSE-LICENSE /usr/share/licenses/goose/LICENSE
RUN printf '#!/bin/sh\nexec /usr/local/bin/python /opt/probe.py capture "$@"\n' > /usr/local/bin/capture-browser \
    && chmod 755 /usr/local/bin/capture-browser
USER 10001:10001
WORKDIR /tmp
EXPOSE 8080 1456
ENTRYPOINT ["python", "/opt/probe.py"]
