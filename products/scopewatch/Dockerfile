# Scopewatch: the judge-facing container.
#
# Build from the REPO ROOT, because the two shared workspace packages live
# outside this product's directory:
#
#   docker buildx build --platform linux/amd64 -f products/scopewatch/Dockerfile .
#   infra/ecr.sh scopewatch --context . --dockerfile products/scopewatch/Dockerfile
#
# linux/amd64 is not a preference. App Runner has no arm64 runtime, and an
# arm64 image fails at deploy time rather than at build time, which is the
# expensive way to find out.
#
# Two things are baked in so a cold start needs no network and no upload: the
# YOLOX-tiny ONNX weights (Apache-2.0, Megvii - there is no AGPL anywhere in
# this image) and a sample laparoscopic clip. A judge opens the URL and presses
# run.

FROM --platform=linux/amd64 python:3.13-slim-bookworm AS build

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

# libglib2.0-0 is here as well as in the runtime stage so that the OpenCV
# version assertion below can actually import cv2. opencv-python-headless
# carries no libGL dependency, but it still links against glib's thread
# library, and python:slim does not ship it.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# /app in both stages, and the same path in both. The product is installed
# editable, so scopewatch.service resolves web/, media/ and models/ relative to
# its own __file__; if the source moved between stages those lookups would come
# out somewhere in site-packages and the sample clip would 404.
WORKDIR /app

COPY constraints.txt /app/constraints.txt
COPY packages/visioncore /app/packages/visioncore
COPY packages/servicekit /app/packages/servicekit
COPY products/scopewatch /app/products/scopewatch

# The pins are repeated here rather than left to the pyproject files on
# purpose. opencv-python-headless unpinned resolves to 4.14.x - which shipped
# after 5.0.0 and is a lower version by every ordering pip knows - and that
# silently fails the competition's core requirement. constraints.txt pins the
# transitive set on top.
RUN pip install --constraint /app/constraints.txt \
      "opencv-python-headless==5.0.0.93" \
      "numpy==2.5.3" \
      "fastapi==0.141.1" \
      "uvicorn[standard]==0.53.0" \
      "python-multipart==0.0.32" \
      "pydantic==2.13.5" \
 && pip install --constraint /app/constraints.txt --no-deps \
      /app/packages/visioncore \
      /app/packages/servicekit \
 && pip install --no-deps --editable /app/products/scopewatch

# One check that covers four ways this image can be wrong: OpenCV is not 5.x,
# the editable install points somewhere unexpected, the model did not make it
# into the context, or the sample clip did not. Failing here costs a minute;
# failing in App Runner costs fifteen.
RUN python -c "\
import cv2, pathlib, scopewatch; \
assert cv2.__version__.startswith('5.'), 'got OpenCV ' + cv2.__version__ + ', need 5.x'; \
root = pathlib.Path(scopewatch.__file__).resolve().parent.parent.parent; \
assert root == pathlib.Path('/app/products/scopewatch'), 'product root resolved to ' + str(root); \
assert (root / 'models' / 'yolox_tiny.onnx').is_file(), 'yolox_tiny.onnx is missing from the image'; \
assert (root / 'media' / 'sample-case.mp4').is_file(), 'sample-case.mp4 is missing from the image'; \
print('opencv', cv2.__version__, 'scopewatch', scopewatch.__version__, 'root', root)"

# ---------------------------------------------------------------------------

FROM --platform=linux/amd64 python:3.13-slim-bookworm AS runtime

# libglib2.0-0 for cv2, curl for the healthcheck. Nothing else.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libglib2.0-0 curl \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 10001 app

COPY --from=build /opt/venv /opt/venv
COPY --from=build /app /app

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    OPENCV26_UPLOAD_DIR=/tmp/scopewatch-uploads \
    SCOPEWATCH_MODEL_DIR=/app/products/scopewatch/models \
    OPENCV26_YOLOX_URI=/app/products/scopewatch/models/yolox_tiny.onnx

ARG GIT_SHA=unknown
ENV OPENCV26_GIT_SHA=${GIT_SHA}

LABEL org.opencontainers.image.title="scopewatch" \
      org.opencontainers.image.description="Blood volume, bleeding onset and a safety checkpoint on the laparoscopic field" \
      org.opencontainers.image.licenses="Apache-2.0"

USER app
WORKDIR /app

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8080/healthz || exit 1

CMD ["uvicorn", "scopewatch.service:app", "--host", "0.0.0.0", "--port", "8080"]
