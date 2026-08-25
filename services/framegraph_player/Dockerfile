# The framegraph player: a character whose body is pre-rendered video.
#
# NOT A VIDEO STREAMER, and the distinction is the whole design. This serves a
# page and a set of fMP4 fragments; the BROWSER is the video engine. MediaSource
# appends fragments and seeks between them, and because every clip begins and
# ends byte-identical to its hub plate there is no cut, no blink and no
# re-fetch. A streaming server would have to re-encode a cut it cannot see.
#
# It is therefore mostly a static file server with a graph attached, which is
# why it needs NO third-party packages at all -- the whole engine is stdlib.
# There is no requirements.txt here on purpose: a hash-locked dependency graph
# that is empty is a file that can only rot.
#
# THE BUNDLE IS MOUNTED, NOT BAKED. A character's clips are its own artefact
# (34MB of 720p fragments for General Montgomery, plus sprites and a manifest),
# and baking them in would mean a new image for every character and a rebuild
# for every re-render. One image, many characters, one volume each.

FROM python:3.12.13-slim-bookworm@sha256:8a7e7cc04fd3e2bd787f7f24e22d5d119aa590d429b50c95dfe12b3abe52f48b AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY frame_player.py /app/frame_player.py
COPY frame_box.py /app/frame_box.py

# Unprivileged, like the channel gateway. It reads one mounted bundle and
# writes nothing.
RUN useradd --create-home --uid 10003 framegraph
USER framegraph

EXPOSE 8902

# 0.0.0.0 INSIDE THE CONTAINER, and only here. The host-side units bind
# loopback because on the M4 a wildcard bind hits EADDRINUSE -- tailscaled
# itself holds the tailnet address for its serve rule. That is a fact about
# that host, not about this program, and inside a container there is no such
# collision: the port is only reachable through whatever compose publishes.
CMD ["python3", "frame_player.py", "/bundle/frame.mp4", "--port", "8902", "--host", "0.0.0.0"]
