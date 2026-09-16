# Scopewatch

**Live: <https://s3vrzphtvv.eu-central-1.awsapprunner.com>** — press "Run the bundled sample". No file of your own is needed.
**Repository: <https://github.com/rogerkorantenng/scopewatch>**

Scopewatch watches the laparoscopic camera that is already in the operating room and
measures the things a surgical team currently estimates by eye.

It does four things, and it is careful about all four:

1. **Blood on the field.** Per frame, as an area and, when there is a scale reference
   in view, as a volume with an interval rather than a single number. Plus a running
   total that is labelled as a lower bound, because blood that goes to suction leaves
   the camera's field and is never counted again.
2. **Bleeding onset.** The timestamp where the rate of change crosses a threshold,
   found by fitting a slope over a sliding window and confirming it with a CUSUM, and
   gated on a camera-motion estimate so a pan across an existing pool is not
   timestamped as a haemorrhage.
3. **Instruments and operative phase.** Instrument shafts from their colour and
   geometry, a scale from their known 5 mm diameter, and a transparent rule-based
   phase model over the whole clip.
4. **A safety checkpoint.** When the phase says the irreversible step is near and no
   safety view has been recorded, Scopewatch holds a checkpoint that a named person
   must confirm or dismiss with a reason. Nothing resolves on a timer.

**Scopewatch is decision support and a retrospective measurement instrument. It is
not a medical device, it has not been through a field trial, it has never been used
on clinical video, and it takes no clinical action of any kind.** See
[docs/report.md](docs/report.md), "Responsible use".

---

## What makes it an agentic entry

The competition's Agentic Vision rubric asks that "image or video results must
influence a subsequent plan, tool call, action, or request for human approval". Three
loops here do that, and each one changes what the pipeline does next rather than what
it prints:

| Perception | Decision | Action |
|---|---|---|
| The coarse pass finds a rate of change | An onset is plausible but poorly localised | Re-open the file and re-read that ten-second window at full frame rate; the dense estimate replaces the coarse one |
| Three consecutive frames refused for fogging | The series cannot be trusted and a white-out looks like a filling field | Suppress the onset detector and raise a clean-lens request instead of an alarm |
| Phase reaches `critical_approach` with no recorded safety view | The irreversible step is near and the checklist step is missing | Hold a checkpoint; produce no further conclusions until a named person confirms or dismisses it with a reason |

A clip with no bleed in it never triggers a second read. That is the test, and it is
in `tests/test_pipeline.py::test_a_quiet_case_never_triggers_a_second_read`.

---

## Pinned dependencies

| Package | Version | Licence | Why pinned |
|---|---|---|---|
| `opencv-python-headless` | **5.0.0.93** | Apache-2.0 | The competition requires OpenCV 5. Version 4.14.0 shipped *after* 5.0.0, so an unpinned `pip install opencv-python` resolves to 4.x and silently fails the core requirement. `import visioncore` raises on a 4.x wheel and `/version` prints what is actually running. |
| `numpy` | 2.5.3 | BSD-3 | Matches the OpenCV 5 wheel's ABI |
| `fastapi` | 0.141.1 | MIT | |
| `uvicorn[standard]` | 0.53.0 | BSD-3 | |
| `python-multipart` | 0.0.32 | Apache-2.0 | |
| `pydantic` | 2.13.5 | MIT | |
| `matplotlib` | 3.11.0 | PSF-based | Evaluation plots only. Never installed into the deployed image. |

Models:

| Model | Licence | Notes |
|---|---|---|
| YOLOX-tiny ONNX, release 0.1.1rc0 | **Apache-2.0** (Megvii) | Baked into the image at `models/yolox_tiny.onnx`, sha256 `427cc366d34e27ff7a03e2899b5e3671425c262ea2291f88bb942bc1cc70b0f7`. Loaded through `cv2.dnn.readNetFromONNX`. |

**No AGPL anywhere.** Nothing in this product imports `ultralytics`, and nothing
depends on FastSAM, YOLOv5/v8/11, YOLO-NAS weights or OpenPose. AGPL-3.0 section 13
extends copyleft to network use, which a hosted demo endpoint triggers.

---

## Run it locally

```bash
cd /path/to/opencv26
uv venv .venv --python 3.13
uv pip install --python .venv/bin/python -e packages/visioncore -e packages/servicekit
uv pip install --python .venv/bin/python -e products/scopewatch

# Confirm you are on OpenCV 5 before anything else.
.venv/bin/python -c "import cv2; print(cv2.__version__)"   # must print 5.0.0

PYTHONPATH=products/scopewatch/src \
  .venv/bin/python -m uvicorn scopewatch.service:app --port 8811
```

Open <http://127.0.0.1:8811> and press **Run the bundled sample**. No file of your own
is needed: a 60-second synthetic case ships in the image.

To see the refusal path, upload `products/scopewatch/media/sample-unmeasurable.mp4`.
Every frame in it is refused for fogging and the run ends with `NO_USABLE_FRAMES`.
That screen is designed, not degraded; it is the tool working.

Command line, without the service:

```bash
PYTHONPATH=products/scopewatch/src .venv/bin/python - <<'PY'
from visioncore import RunRecord, recording
from scopewatch.pipeline import analyse_case, to_record
from scopewatch.config import PipelineParams

record = RunRecord(product="scopewatch")
with recording(record):
    result = analyse_case("products/scopewatch/media/sample-case.mp4",
                          params=PipelineParams(stride=3, use_dnn=False))
to_record(result, record, PipelineParams())
print(record.to_json())
PY
```

---

## Test it

```bash
cd products/scopewatch
PYTHONPATH=src ../../.venv/bin/python -m pytest tests/ -q
```

**126 tests, all passing.** The suite asserts on numbers, not on "it ran": area error
against an area set before the pixels existed, scale error against a shaft whose width
we chose, onset timing against a bleed that starts on a frame we picked, and the
refusal paths for fogging, defocus, occlusion and a missing scale reference. Several
are regression tests for specific bugs, named after the bug: a surface vessel must not
be counted as a pool, a settled pool must not be counted as an occlusion, a camera pan
must not be timestamped as a haemorrhage, and a held checkpoint must survive a hundred
further frames without resolving itself.

Deselect the slow video tests with `-m "not slow"`; they generate real MP4 files and
run the whole pipeline over them, which is most of the wall time.

---

## Re-run the evaluation

```bash
cd products/scopewatch
uv pip install --python ../../.venv/bin/python "matplotlib==3.11.0"
PYTHONPATH=src ../../.venv/bin/python -m scopewatch.evaluate --out docs
```

That writes `docs/evaluation.json` and the plots in `docs/plots/`.
[docs/evaluation.md](docs/evaluation.md) quotes it; if the two ever disagree, the JSON
is right. The running service serves the same JSON at `/api/evaluation`, so the error
bars sit next to the numbers they qualify.

---

## Deploy it

```bash
./infra/deploy.sh
```

Builds the image from the repository root, pushes it to ECR, and creates or updates
the App Runner service at 2 vCPU / 4 GB, tagged `Project=opencv26`. The region comes
from `AWS_REGION` and defaults to `us-east-1`; the live service runs in `eu-central-1`
because the account is capped at two App Runner services per region and all three US
regions were full. See [docs/costs.md](docs/costs.md).
Costs and the exact resources created are in [docs/costs.md](docs/costs.md).

---

## Open to-do for the maintainer: dataset access

**This entry has no clinical video in it and the evaluation says so on every page.**
The published laparoscopic datasets that carry the labels Scopewatch would need sit
behind registration forms, and the request has not been completed:

- **Endoscapes** — CAMMA, University of Strasbourg. Carries the critical-view-of-safety
  annotations. Licence **CC BY-NC-SA 4.0**, confirmed from the repository's own LICENSE
  file at <https://github.com/CAMMA-public/Endoscapes>. Requires a signed access form.
- **CholecT50** — same group. Instrument, verb and target triplet annotations, which is
  what a learned instrument channel would train on. Licence **CC BY-NC-SA 4.0**,
  confirmed at <https://github.com/CAMMA-public/cholect50>. Requires a signed form.
- **Cholec80** — same group. Phase and tool annotations. Licence not separately
  verified; assume CC BY-NC-SA 4.0 and check before use.

Three consequences to plan around before anyone relies on these:

1. **Non-commercial.** Fine for a competition entry, and a blocker for a product
   without new data.
2. **ShareAlike.** Derivatives of the dataset must go out under the same licence, so be
   deliberate about what gets published alongside them.
3. **Lead time.** The forms take days. Start the request before writing the code that
   depends on it.

Until then, everything in [docs/evaluation.md](docs/evaluation.md) is measured on
synthetic scenes generated by `scopewatch.synth`, where each quantity is set before
the pixels exist. That is real evidence about the estimator and no evidence at all
about tissue, and the document is explicit about the difference.

---

## Where things are

```
products/scopewatch/
  src/scopewatch/
    config.py        every threshold, with the reason it has that value
    quality.py       the refusal gates: focus, fog, occlusion, exposure
    blood.py         segmentation, area, and area-to-volume with its uncertainty
    instruments.py   shafts, the scale they give, and the YOLOX channel
    onset.py         smoothing, camera motion, rate fitting, CUSUM
    phase.py         the operative-phase state machine
    agent.py         perceive, decide, act, ask a person, record
    pipeline.py      the two passes and the RunRecord they produce
    synth.py         synthetic scenes whose truth is known by construction
    evaluate.py      the seven experiments and the plots
    service.py       the FastAPI app and the two checkpoint routes
  web/               the interface: dark, theatre-instrument, one signature element
  tests/             pytest, real assertions on numbers
  media/             the bundled sample clip and the unmeasurable one
  docs/              report, architecture, evaluation, costs, devpost, narration, deck
  infra/deploy.sh    ECR then App Runner, idempotent
```
