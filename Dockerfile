FROM debian:trixie-slim AS build
# MKV_VERSION=latest -> neueste Version wird von makemkv.com/download ermittelt
ARG MKV_VERSION=latest
# MakeMKV-EULA (https://www.makemkv.com/eula/) muss bewusst mit ACCEPT_EULA=yes akzeptiert werden
ARG ACCEPT_EULA=no
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential pkg-config ca-certificates curl \
      libssl-dev libexpat1-dev zlib1g-dev libavcodec-dev libavutil-dev \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src
RUN set -e; \
    [ "$ACCEPT_EULA" = "yes" ] || { echo "FEHLER: MakeMKV-EULA nicht akzeptiert (--build-arg ACCEPT_EULA=yes)"; exit 1; }; \
    v="$MKV_VERSION"; \
    if [ "$v" = latest ]; then \
      v=$(curl -fsSL https://www.makemkv.com/download/ | grep -oE 'MakeMKV [0-9]+\.[0-9]+\.[0-9]+ for Windows' | head -1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+'); \
    fi; \
    echo "MakeMKV $v"; echo "$v" > /src/version; \
    curl -fsSL https://www.makemkv.com/download/makemkv-oss-$v.tar.gz | tar xz; \
    curl -fsSL https://www.makemkv.com/download/makemkv-bin-$v.tar.gz | tar xz; \
    cd makemkv-oss-$v && ./configure --disable-gui && make -j"$(nproc)" && make install; \
    cd ../makemkv-bin-$v && mkdir -p tmp && echo accepted > tmp/eula_accepted && make install

FROM debian:trixie-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 python3-pip python3-venv ca-certificates curl libssl3t64 libexpat1 zlib1g ffmpeg \
    && rm -rf /var/lib/apt/lists/*
COPY --from=build /usr/bin/makemkvcon /usr/bin/makemkvcon
COPY --from=build /usr/lib/libmakemkv.so.1 /usr/lib/libdriveio.so.0 /usr/lib/libmmbd.so.0 /usr/lib/
COPY --from=build /usr/share/MakeMKV /usr/share/MakeMKV
COPY --from=build /src/version /etc/makemkv-version
RUN ldconfig
RUN python3 -m venv /opt/venv && /opt/venv/bin/pip install --no-cache-dir fastapi "uvicorn[standard]"
COPY app /app
WORKDIR /app
ENV PATH=/opt/venv/bin:$PATH HOME=/data
CMD ["uvicorn","main:app","--host","0.0.0.0","--port","8780"]
