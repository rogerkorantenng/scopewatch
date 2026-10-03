# Scopewatch: measuring the laparoscopic operating field

Technical report, OpenCV AI Competition 2026.

---

## 0. Summary

Scopewatch measures the laparoscopic operating field from the camera already in the
room: the share of the visible field covered in blood, how fast that share is changing,
and when the picture does not support an answer.

**Results on sixteen openly licensed real surgical clips**, against hand-drawn masks on
64 labelled frames:

| | Held-out clips | Dev clips | All laparoscopic |
|---|---|---|---|
| Blood-pixel precision | **63.6%** | 82.2% | **78.2%** |
| Blood-pixel recall | 7.7% | 40.1% | 23.2% |

The decision rule is colour. A pixel is blood when its Lab chroma clears an absolute
floor, its chroma-to-lightness ratio clears a multiple of the scene's own median, and
its hue sits inside a band around that scene median. Its three constants are selected by
maximising F-0.5 under leave-one-clip-out across the corpus, weighting precision over
recall, because a surgical overlay should be right when it marks something.

A learned alternative was built and measured against it: MobileNetV3 with an FPN
decoder, trained in PyTorch, exported to ONNX and run through OpenCV 5's own `cv2.dnn`.
On the same held-out frames it reached 5.9% precision. The colour rule is what ships.

Volume in millilitres is refused on every clip in this corpus, because the
instrument-shaft scale varies by 29 to 61% within a single clip. The product prints
`CANNOT_MEASURE` and names the reason rather than a number it cannot support.

Everything runs on OpenCV 5.0.0, pinned, on AWS App Runner in eu-central-1.

## 1. The problem

**Blood loss is estimated by eye, and the eye is wrong.** Edilu R et al., comparing
visual estimation against haematocrit change in 100 caesarean deliveries in northern
Uganda, found visual estimation underestimated loss in 90% of cases, and that 21% had
undiagnosed postpartum haemorrhage over 1,000 ml — of whom, by eye, none had
haemorrhaged at all (*Therapeutic Advances in Reproductive Health*, Oct 2024,
DOI 10.1177/26334941241289552). Tan AWM et al. point the same way at KK Women's and
Children's Hospital, Singapore (*Acta Obstet Gynecol Scand*, Nov 2025, PMID 40999760);
their differences were not statistically significant, so only the direction is cited
here. The profession already knows: Biller-Friedmann and Bayerlein, "Visual estimation
of blood losses: Known high error rate — How can it be improved?" (*Die
Anaesthesiologie* 74(6), June 2025).

Measured alternatives exist — gravimetric weighing of gauze, haematocrit-based
calculation — and both remain underused, because measurement costs time and attention
the operating team does not have while operating. A camera already in the room costs
neither.

**The safety step is skipped exactly where it is needed most.** Aguilera M et al.
reviewed 548 resident-performed laparoscopic cholecystectomy videos at Pontificia
Universidad Católica de Chile: the critical view of safety was achieved in 61% of cases,
and in the hardest tier, 14% (*Surgical Endoscopy*, Aug 2026,
DOI 10.1007/s00464-026-13243-0).

**The bar is low and credible.** WHO reports that complications follow up to 25% of
inpatient operations, and that the Surgical Safety Checklist — two minutes of paper —
reduced complications and mortality by over 30%. Scopewatch is a checklist step a camera
can notice has not happened.

---

## 2. Users

**The operating surgeon and the scrub team, after the case.** The primary use is review:
a timeline with the blood on the field measured rather than recalled, the bleeding onset
timestamped, and a record of what the team was asked and what they answered.

**The surgical trainer.** The Chilean benchmark works because asynchronous video review
works. Turning a 45-minute recording into a phase ribbon, a field trace and a short
event log makes that review affordable enough to do routinely.

**The person who answers the checkpoint.** The only user who interacts with Scopewatch
during a case, and the interaction is one question with two answers, one of which
requires a written reason. A checkpoint that fires two minutes early gets dismissed out
of habit, so the approach window is deliberately short.

---

## 3. Architecture

Full diagrams in [architecture.md](architecture.md). In prose:

A clip is decimated and read frame by frame. Each frame passes five quality gates (focus, fog, occlusion, exposure clipping and
out of domain)
before anything measures it, and a frame that fails a gate produces a named refusal
rather than a number. A frame that passes has its instrument shafts found, and a shaft
crossing the edge of the projected circle supplies a scale, because laparoscopic shafts
are manufactured at a known diameter. Blood is segmented by two votes, area converted
to a volume interval, and the per-frame volumes become a time series that is smoothed,
differentiated over a sliding window, and tested for a change point. In parallel,
instrument counts and shaft widths drive a phase state machine. The agent loop watches
all of it and takes three kinds of action, one of which is to stop and ask a person.

The product sits on two shared packages built for this competition: `visioncore` (the
OpenCV 5 primitives, the run record, the stage timers, the YOLOX runner) and
`servicekit` (the FastAPI shell: upload, job queue, Server-Sent Events progress,
evidence endpoint). Scopewatch adds its own interface and two routes for the
checkpoint, and edits neither shared package.

---

## 4. The OpenCV 5 implementation, in detail

### 4.1 The lit field, and why it is not the frame

A laparoscope projects a circle into a rectangular sensor. The corners are not dark
tissue; they are no data. Counting them as "not blood" deflates every area fraction by
the same twenty per cent, invisibly and consistently. So the lit region is recovered
once per frame - `cvtColor`, a threshold at 16 levels, `morphologyEx` open and close
with a 9x9 ellipse, then `connectedComponentsWithStats` keeping the largest component -
and every fraction in this product is taken against it. The fallback when the lit
region is implausibly small is the whole frame, which is what an already-cropped clip
needs.

That choice has a second consequence that took a bug to find. An instrument entering
through a port crosses the edge of the **circle**, several hundred pixels from the edge
of the frame. The first version of the shaft detector tested "does this component touch
the border" against the image rectangle, found nothing, and silently produced no scale
at all. `instruments.field_boundary` now builds a ring by subtracting an eroded copy of
the lit mask from itself, and the test that pins it asserts the ring does not hug the
image edge.

### 4.2 Blood segmentation

Everything in an abdomen is red, so redness alone is not a discriminator. Seven
candidates were implemented and scored: a fixed HSV hue range, Lab a*, YCrCb Cr,
normalised redness (R-G)/(R+G), Lab a* with L*, normalised redness with a flattened L*,
and the chroma-scene rule that ships.

A pixel is blood when it clears three tests at once: Lab chroma above an absolute floor
of 42, chroma per unit lightness at least 1.55 times the scene's own median, and a Lab
hue inside 20 degrees of that scene median. Blood is deeply coloured for how light it
is; shadow is dark and grey; pink tissue is coloured but light. Darkness is never used
as evidence. The constants come from maximising F-0.5 under leave-one-clip-out, which
weights precision over recall.

Four findings from the sweep shaped the implementation.

**Otsu is the wrong tool when the target is a minority class.** Otsu assumes two
comparable populations. A frame with a large pool has blood on a few per cent of the lit
field, so Otsu splits the *tissue* along the fat-against-vessel axis and returns half the
abdomen with complete confidence. Every candidate thresholds against the **tissue mode**
instead: find the dominant histogram peak, measure its spread on the side the target
cannot contaminate, and take what lies four sigma above it. That works when the target
is a tenth of a per cent of the field, and returns nothing when it is absent.

**CIE Lab's chroma axes compress dark colours.** A dark saturated red lands at an a* of
about 165 while perfused tissue sits at 149 with a spread of 5. Four sigma above the
tissue mode is 167, so the pool falls on the wrong side. On four of twenty-four sweep
scenes that returned an empty mask for a field a quarter covered in blood. The
normalised redness ratio has no such compression, being invariant both to the scope's
automatic gain and to how dark the surface is.

**The scope's own lighting looks like blood.** The light source sits at the tip,
centimetres from the tissue, so the periphery is darker than the centre by a factor of
two, and a darkness vote cannot tell that from a pool. `blood.flatten_lightness` divides
L* by a heavily blurred illumination estimate taken with the candidate region
**excluded** — leave it in and a pool covering a tenth of the field drags the local
estimate down around itself, under-measuring a large haemorrhage by a fifth.

**A surface vessel is redder and darker than the tissue around it**, and is not blood
loss. What separates them is shape: a pool has extent in two dimensions, a vessel in
one. Each surviving component is measured on its own medial axis with
`distanceTransform`, and a component whose widest point is under nine pixels is a line.

Specular highlights are near-white and low-chroma and sit inside pools as often as on
tissue. They are excluded from both the mask and the field it is measured against, and
the count is reported so the exclusion is visible.

### 4.3 Scale, and its uncertainty

A laparoscopic instrument shaft is manufactured at a known outer diameter — 5 mm for
common working instruments, 3 mm paediatric, 10 mm devices. That makes every instrument
in view a calibration target, and it is how Scopewatch gets millimetres per pixel out of
monocular video with nothing added to the theatre: no marker, no chessboard, no second
camera.

The scale is read edge-to-edge from saturation profiles across the shaft axis, measured
near where each instrument enters the field so crossed instruments are still apart. A
medial-axis width via `distanceTransform` is used separately for the instrument count
and the phase features. On a wet steel shaft under a scope's light only the stripe
facing the light passes a brightness test, so a medial-axis width alone reads about half
the shaft. Pixel floors scale with the frame, because an area floor set on 960-pixel
frames discards every shaft on a 320×240 clip.

Two geometric decisions are stated rather than hidden.

**Crossed instruments are kept and flagged as merged.** Two instruments working on the
same structure touch, and the union of two crossed shafts is not elongated, so an
elongation test rejects both and loses the scale with them. The median medial-axis width
still lands on the shaft width because most of the ridge runs along a shaft; the
wide-device cue reads the 95th percentile instead, because when a clip applier crosses a
grasper only the upper tail sees it.

**The scale is isotropic and local.** It says how many millimetres a pixel spans at that
shaft's distance, and nothing about the orientation of the surface the blood lies on. A
pool on peritoneum tilted away from the camera projects smaller than it is, by cos(tilt).
A single camera with no planar reference cannot recover that tilt, so it is bounded
rather than estimated: beyond about forty degrees a surgeon repositions anyway, so the
upper end of every area interval is widened by 1/cos(40°) = 1.305. The lower end is not,
because tilt can only make the true area larger than the projection.

### 4.4 Area to volume

Pixel area is not millilitres, and on this corpus the volume is withheld. A shaft's
apparent width moves with its distance from the lens, and the blood lies at another
distance again, so the per-frame scale on real clips varies by 29 to 61% (robust
coefficient of variation). A volume is computed only when at least 25% of measurable
frames and at least 50 frames carry a shaft scale and that variation is under 25%, at
the case's median scale. Otherwise the record carries `CANNOT_MEASURE` with
`NO_SCALE_REFERENCE` or `SCALE_INCONSISTENT`. No clip in this corpus passes.

Where a scale is supplied, area becomes volume through a depth assumption, and the
interval it produces is reported with the number rather than behind it.

### 4.5 Bleeding onset

The series is the blood-covered share of the field, in percentage points, with a default
threshold of 8 points a minute. Frames that cannot be measured hold the last measured
value rather than entering as zero; zeros turn every refusal gap into a fall and a rise.

Two obvious approaches are both wrong. Thresholding the volume answers "when was there a
lot of blood", which is minutes after the event and is the delay a surgeon already has
by eye. Thresholding the raw first difference confuses a camera pan with a bleed,
because a scope panning across an existing pool produces the same positive slope.

So: a least-squares slope over a four-second **trailing** window — trailing, because a
theatre instrument cannot look into the future — confirmed by a one-sided CUSUM on the
same series. Both must agree. Every candidate frame is gated on a global motion estimate
from `cv2.phaseCorrelate` on a 256-pixel Hanning window, which costs well under a
millisecond and answers the only question the pipeline needs: did the whole field move.

The CUSUM's slack and decision interval scale from the series' own noise, using the
**median** absolute first difference rather than the standard deviation — precisely
because the change being hunted is in the tail, and a standard deviation computed over a
series containing the bleed is inflated by the bleed, so the detector then needs a bigger
bleed to notice it.

The threshold follows from the physics. A laparoscope at working distance sees four to
eight centimetres across; at a 2 mm film that whole field holds only a few millilitres,
and everything beyond has gone to suction and was never on camera. A threshold set in
millilitres per minute is one the field can physically never reach, so the default is
expressed as blood visible on the field, and the interface says which quantity that is.

When no onset is declared, the reason counts, for every frame whose rate crossed the
threshold, the gate that stopped it: refused frame, camera motion, too-small blood area,
an instrument entering or leaving, or no CUSUM confirmation.

### 4.6 Instruments, phase, and the DNN channel

The instrument channel is classical — low-chroma, bright, elongated components crossing
into the lit field — and the measurement depends on it, because it supplies the scale.

**YOLOX-tiny runs through `cv2.dnn` on every tenth kept frame**, and this report is
explicit about its role. The official weights are trained on COCO, which has no surgical
instrument classes, so it cannot name a Maryland dissector and nothing here implies it
can: every detection carries the note "COCO class; not a surgical instrument taxonomy",
and a test fails if that note is removed. What it contributes is a licence-clean,
ONNX-only, OpenCV-5 DNN path — `readNetFromCaffe` and `readNetFromDarknet` were removed
in 5.x, so ONNX is the only option, and YOLOX's Apache-2.0 export is the natural choice
over AGPL Ultralytics weights — and a measured `cv2.dnn` latency on the new engine. A
surgical instrument detector would need CholecT50's triplet annotations, which sit behind
a registration this entry has not completed.

**The automatic checkpoint is off by default.** The wide-device cue compares edge widths
with edge widths and must hold for 1.5 seconds; a dwell timer can only arm it, never
trigger it, and a test pins that dissection alone never reaches the critical approach.
Instrument width still cannot separate a clip applier from a grasper nearer the lens,
which is why it ships off.

## 5. AWS deployment

Account `<aws-account-id>`, region **eu-central-1**, everything tagged `Project=opencv26`.

- **ECR** repository `opencv26/scopewatch`. The image carries
  `opencv-python-headless==5.0.0.93`, the YOLOX-tiny ONNX file with its sha256 checked
  at build time, and the bundled sample clip.
- **App Runner** service at 2 vCPU / 4 GB, always on, x86_64. HTTPS with a managed
  certificate and no load balancer.
- **S3** bucket `opencv26-artifacts-<aws-account-id>` under the `scopewatch/` prefix.
- **CloudWatch Logs** for application and service logs.

**Live at <https://s3vrzphtvv.eu-central-1.awsapprunner.com>**, `/version` git_sha
`06a2f28`. The endpoint works from a cold start with no local file: the sample clip is
inside the image and a button runs it. `infra/deploy.sh` is idempotent — it builds from
the repository root, pushes, creates or updates the service, and polls until RUNNING.

Two deployment choices worth defending. **App Runner rather than Lambda**: a judging
window is two weeks of unattended availability, and a one-to-two gigabyte OpenCV
container's cold start is unmeasured — a judge who waits thirty seconds for a first
response has already formed a view. **x86_64 rather than Graviton**: App Runner exposes
no ARM option in its pricing, its FAQ or its API parameters. The aarch64 OpenCV 5 wheel
does ship Arm's KleidiCV HAL, so a real Graviton story is available on EC2 or ECS; it is
not available here.

**Running cost** is about $24.50 a month: App Runner at 2 vCPU / 4 GB always on is
$24.28 of it, with ECR storage and S3 making up the rest. Running the same service at
0.25 vCPU / 0.5 GB would cost about $2.52 a month idle; the larger sizing is the trade
accepted for a demo that responds on the first click rather than after a cold start.

The region is a deviation worth stating. App Runner on this account is capped at two
services per region and all three US regions were at that cap, so eu-central-1 was used.
For a US judge that is about 100 ms of round-trip latency; the deploy script takes its
region from the environment.

---

## 6. Evaluation

Full method, numbers and plots: [evaluation.md](evaluation.md). Machine-readable:
`docs/evaluation.json`, which the running service serves at `/api/evaluation`.

Sixteen openly licensed clips. Blood is scored against polygons drawn on 64 fixed frames
by a labeller who never saw the product's output, split **by clip** into dev and test, so
that a shared scope, light source and patient cannot leak between the halves.

| | Dev clips | Held-out clips | All laparoscopic |
|---|---|---|---|
| Blood-pixel precision | 82.2% | **63.6%** | **78.2%** |
| Blood-pixel recall | 40.1% | 7.7% | 23.2% |

Behaviour across all sixteen: the open-surgery clip is refused `OUT_OF_DOMAIN`; every
clip reads `CANNOT_MEASURE` for volume, because none passes the scale gate; the onset
does not fire, and the reason names the gate that held it on each crossing.

Synthetic scenes cover area, scale, volume-interval coverage, refusal sweeps, onset
timing, phase confusion and checkpoint timing, on fields where every quantity is set
before the pixels exist. That is evidence about the arithmetic and none about tissue.

No real clip has a known blood volume, so no volume accuracy on real footage is claimed.
The labelled clinical datasets — Endoscapes, CholecT50 — are CC BY-NC-SA behind
registration forms this entry has not completed.

---

## 7. Limitations and responsible use

**What it does not do well.**

- Tuned to be right when it marks something, so some blood is left unmarked: 63.6%
  precision on the held-out clips.
- No clip in the corpus passes the scale gate, so no millilitre figure is shown, and no
  millilitre figure has ever been checked against a measured one.
- The bleeding onset does not fire on a moving laparoscope. No stabilisation or
  registration is attempted; that is the next step.
- Instrument width cannot tell a clip applier from a grasper nearer the lens, so the
  safety checkpoint is off by default and marked experimental.
- The fog gate is validated on synthetic haze only; no real clip in the corpus had haze.
- Everything rests on 64 labelled frames from a single labeller across sixteen clips,
  and that labeller was not a surgeon.

**Scopewatch is not a medical device.** It has no regulatory clearance, has not been
through a field trial, and is not offered for intra-operative decision-making. It is a
retrospective measurement and training instrument.

**It takes no clinical action.** Every checkpoint is resolved by a named human. None
expires, times out or resolves itself. The service refuses an anonymous confirmation and
refuses a dismissal carrying no reason; both are tested, as is the case where a held
checkpoint is fed a hundred further frames and stays held.

**No identifiable people.** The sample media are synthetic scenes drawn with OpenCV
primitives. The real operative material in this repository is six small test crops from
openly licensed clips, each credited in `realdata.CLIPS`.
