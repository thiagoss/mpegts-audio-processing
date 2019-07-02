FROM debian:sid-20190610-slim  AS builder

RUN \
    apt-get update -y && \
    apt-get install -y libgstreamer1.0-dev libgstreamer-plugins-base1.0-dev \
        git build-essential automake libtool gtk-doc-tools

RUN \
    git clone git://github.com/thiagoss/gst-plugins-bad.git && \
    cd gst-plugins-bad && \
    git checkout 1.14-mpegts-preserve-ts && \
    ./autogen.sh --prefix=/usr && \
    make && \
    make install

FROM debian:sid-20190610-slim

RUN \
    apt-get update -y && \
    apt-get install -y gstreamer1.0-tools gstreamer1.0-plugins-base \
        gstreamer1.0-plugins-good gstreamer1.0-plugins-bad \
        python3 gir1.2-gstreamer-1.0 python3-gi

COPY --from=builder /usr/lib/gstreamer-1.0/libgstmpegtsdemux.* /usr/lib/x86_64-linux-gnu/gstreamer-1.0/

WORKDIR /gstreamer
ADD transcodempegts.py .
ADD sample.ts .

ENTRYPOINT python3 transcodempegts.py sample.ts
