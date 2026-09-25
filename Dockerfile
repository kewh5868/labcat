# Linux image, built for amd64 and arm64. Host needs a compatible Docker runtime.
FROM node:24-slim@sha256:2fe369e969550cde8e867afc3fe370b260140cab4a23d467074295b42163d553 AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim@sha256:9d2e5553305c7c7b0097999bb17187c69b921ccd6bc9d40e4bb5ebe652c00285 AS build
WORKDIR /build
COPY requirements/build.lock /build/requirements/build.lock
RUN python -m pip install --no-cache-dir --require-hashes -r requirements/build.lock
COPY pyproject.toml README.md LICENSE.rst ./
COPY src ./src
COPY --from=frontend /src/labcat/static ./src/labcat/static
RUN python -m pip wheel --no-deps --no-build-isolation --wheel-dir /wheels .

# Portable upstream binaries are fetched only at build time and hash verified.
FROM python:3.13-slim@sha256:9d2e5553305c7c7b0097999bb17187c69b921ccd6bc9d40e4bb5ebe652c00285 AS agents
ARG TARGETARCH
COPY scripts/install_goose.py /build/install_goose.py
RUN python /build/install_goose.py "$TARGETARCH"

FROM python:3.13-slim@sha256:9d2e5553305c7c7b0097999bb17187c69b921ccd6bc9d40e4bb5ebe652c00285 AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 LABCAT_DATA_DIR=/var/lib/labcat LABCAT_AGENT_ENGINE=goose
WORKDIR /app
COPY requirements/runtime.lock /app/requirements/runtime.lock
RUN python -m pip install --no-cache-dir --require-hashes -r requirements/runtime.lock
COPY --from=build /wheels /wheels
COPY --from=agents /agent-bin/goose /usr/local/bin/goose
COPY --from=agents /agent-bin/codex /usr/local/bin/codex
COPY third_party/ /usr/share/licenses/labcat/
RUN python -m pip install --no-cache-dir --no-deps /wheels/*.whl \
    && rm -rf /wheels \
    && groupadd --gid 10001 labcat \
    && useradd --uid 10001 --gid labcat --create-home labcat \
    && install -d -m 0700 -o 10001 -g 10001 /var/lib/labcat
USER labcat
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"
ENTRYPOINT ["labcat"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8000"]
