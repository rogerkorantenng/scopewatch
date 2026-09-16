# Scopewatch

An entry for the OpenCV AI Competition 2026. Scopewatch watches the laparoscopic
camera that is already in the operating room and measures the things a surgical team
currently estimates by eye: the blood on the field, with an uncertainty range rather
than a single number; the timestamp where the rate of change crosses a threshold; the
instruments and the operative phase; and a safety checkpoint that a named person must
answer before the irreversible step.

**Scopewatch is decision support and a retrospective measurement instrument. It is not
a medical device, it has never been run on clinical video, and it takes no clinical
action of any kind.**

## Start here

| | |
|---|---|
| **What it is, how to run it, how to test it** | [`products/scopewatch/README.md`](products/scopewatch/README.md) |
| **Technical report** | [`products/scopewatch/docs/report.md`](products/scopewatch/docs/report.md) |
| **Architecture, with the OpenCV 5, agent and AWS diagrams** | [`products/scopewatch/docs/architecture.md`](products/scopewatch/docs/architecture.md) |
| **Evaluation: method, numbers, plots and failure cases** | [`products/scopewatch/docs/evaluation.md`](products/scopewatch/docs/evaluation.md) |
| **What it costs to run** | [`products/scopewatch/docs/costs.md`](products/scopewatch/docs/costs.md) |

## Why the repository has this shape

The product is at `products/scopewatch`, and the two packages beside it are the shared
foundation it is built on: `visioncore` holds the OpenCV 5 primitives, the run record
and the model runner, and `servicekit` holds the FastAPI shell. They are laid out this
way because the Docker build and the deployment script expect these paths, and because
keeping them here makes the repository a complete, buildable copy rather than a
fragment that needs three other checkouts to work.

## The one-line version

```bash
uv venv .venv --python 3.13
uv pip install --python .venv/bin/python -e packages/visioncore -e packages/servicekit -e products/scopewatch
.venv/bin/python -c "import cv2; print(cv2.__version__)"   # must print 5.0.0
PYTHONPATH=products/scopewatch/src .venv/bin/python -m uvicorn scopewatch.service:app --port 8811
```

Then open the page and press **Run the bundled sample**. No file of your own is needed.
