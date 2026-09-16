# Scopewatch

**Live: <https://s3vrzphtvv.eu-central-1.awsapprunner.com>** — press "Run the bundled sample". No file of your own is needed.
**Repository: <https://github.com/rogerkorantenng/scopewatch>**

Scopewatch watches the laparoscopic camera that is already in the operating room and
measures what it can honestly measure there.

**Read this before anything else.** Scopewatch was built and evaluated on synthetic
scenes, where it worked. Then it was run on sixteen real, openly licensed surgical
clips, and it did not: it read a bleeding field as 0.00 ml, rim shadow as 9.97 ml, and
held its safety checkpoint on a timer. Every one of those failures has been traced to a
cause, fixed or gated, and pinned by a test on a real frame. What it outputs has changed
because of them. The full account is Part A of [docs/evaluation.md](docs/evaluation.md).
**No real clip has a known blood volume, so no millilitre figure from Scopewatch has
ever been checked against a real one.**

What it does now:

1. **Blood-covered field.** Per frame, the share of the visible field segmented as
   blood, and how fast that share changes. On hand-labelled frames from held-out real
   clips the segmentation's pixel precision is 13% and its recall 11% (the old one: 0%
   and 0%). It separates blood from shadow and from a port sleeve; it does not reliably
   separate blood from red tissue. That number is shown next to the measurement.
2. **Volume, usually refused.** Millilitres appear only when the instrument-shaft scale
   is present on enough frames and steady across the case, and are labelled as never
   validated on real footage. Otherwise the row says `CANNOT_MEASURE` and why. On all
   sixteen real clips it says `CANNOT_MEASURE`: shafts at different distances from the
   lens give scales that vary by 29 to 61% within a clip.
3. **Bleeding onset.** A windowed slope on the blood-covered share, confirmed by a
   CUSUM, gated on camera motion and instrument changes. When it does not fire, the
   reason names the gates that stopped it. On real footage it has not fired: the camera
   is almost never still for the fit window.
4. **Refusals.** Focus, fog, occlusion, exposure, and now `OUT_OF_DOMAIN` for open
   surgery, drapes and gloved hands.
5. **An experimental safety checkpoint, off by default.** When switched on, a phase
   model driven by instrument width can hold a checkpoint that a named person must
   confirm or dismiss with a reason. On real video instrument width cannot tell a clip
   applier from a grasper nearer the lens, so it is not on unless asked for.

**Scopewatch is a retrospective measurement instrument. It is not a medical device, it
has not been through a field trial, and it takes no clinical action of any kind.** See
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
| Phase reaches `critical_approach` with no recorded safety view (only with `auto_checkpoint` on) | The irreversible step may be near and the checklist step is missing | Hold a checkpoint; produce no further conclusions until a named person confirms or dismisses it with a reason |

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
../../.venv/bin/ruff check .
```

**TESTCOUNT tests, all passing, and ruff clean.** The suite asserts on numbers, not on
"it ran". `tests/test_real_footage.py` holds the regression tests from real video,
on small credited crops in `tests/fixtures/real/`: a pooled-blood field that used to
read as nothing, rim shadow and a port sleeve that used to read as blood, gloved hands
that must be refused, and a wet shaft whose steel mask is half its true width. Others
pin the onset reason naming the gate that stopped it, refusal gaps not becoming slopes,
and ten minutes of dissection never reaching the critical approach on the dwell timer
alone.

Deselect the slow video tests with `-m "not slow"`.

---

## Re-run the evaluations

Real footage (clips not included; `src/scopewatch/realdata.py` lists every source,
author and licence):

```bash
PYTHONPATH=src ../../.venv/bin/python -m scopewatch.realeval --media /path/to/clips --out runs/after
```

Synthetic scenes, which also fold `docs/real-evaluation.json` into `docs/evaluation.json`:

```bash
uv pip install --python ../../.venv/bin/python "matplotlib==3.11.0"
PYTHONPATH=src ../../.venv/bin/python -m scopewatch.evaluate --out docs
```

The running service serves `docs/evaluation.json` at `/api/evaluation`.

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

The real-footage evaluation uses sixteen openly licensed clips with 64 hand-labelled
frames and no known blood volumes. The published laparoscopic datasets with expert
labels sit behind registration forms, and the request has not been completed:

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

Until then, Part A of [docs/evaluation.md](docs/evaluation.md) is the only evidence
about real tissue, and it rests on one labeller and 64 frames.

---

## Where things are

```
products/scopewatch/
  src/scopewatch/
    config.py        every threshold, with the reason it has that value
    quality.py       the refusal gates: focus, fog, occlusion, exposure, out of domain
    blood.py         segmentation, area, and area-to-volume with its uncertainty
    instruments.py   shafts, the scale they give, and the YOLOX channel
    onset.py         smoothing, camera motion, rate fitting, CUSUM
    phase.py         the operative-phase state machine
    agent.py         perceive, decide, act, ask a person, record
    pipeline.py      the two passes and the RunRecord they produce
    synth.py         synthetic scenes whose truth is known by construction
    evaluate.py      the synthetic experiments and the plots
    realdata.py      the sixteen real clips, their licences, the label sample
    realeval.py      the real-footage evaluation and its before-and-after summary
    service.py       the FastAPI app and the two checkpoint routes
  web/               the interface: dark, theatre-instrument, one signature element
  tests/             pytest, real assertions on numbers; fixtures/real has credited crops
  eval/real/         hand-drawn blood labels and visible-bleeding notes for the real clips
  media/             the bundled sample clip and the unmeasurable one
  docs/              report, architecture, evaluation, costs, devpost, narration, deck
  infra/deploy.sh    ECR then App Runner, idempotent
```
