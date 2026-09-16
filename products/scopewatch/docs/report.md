# Scopewatch: measuring the laparoscopic operating field

Technical report, OpenCV AI Competition 2026.

---

## 1. The problem, with evidence

### 1.1 Blood loss is estimated by eye, and the eye is wrong

Edilu R, et al. "Comparing visual estimation and hematocrit change in the assessment
of blood loss among women undergoing cesarean delivery in a tertiary facility in
northern Uganda." *Therapeutic Advances in Reproductive Health*, 17 October 2024.
PMID 39435121. DOI 10.1177/26334941241289552.

> "Visual estimation underestimated blood loss in 90% of cases (n = 100), and 21%
> (n = 21) had undiagnosed PPH (>1000 ml blood loss). None of the respondents had
> PPH (>1000 ml blood loss) following vEBL."

That last sentence is the case for this product in one line. By eye, nobody
haemorrhaged. By measurement, one in five did.

A second study points the same way: Tan AWM, et al., *Acta Obstetricia et Gynecologica
Scandinavica*, November 2025, PMID 40999760, at KK Women's and Children's Hospital in
Singapore.

> "vEBL appears to grossly underestimate actual blood loss when compared with QBL and
> cEBL methods... reliance solely on vEBL may lead to under-recognition and delayed
> management of PPH."

That study's differences were **not statistically significant** and its confidence
intervals were very wide, so its direction and its conclusion are quoted here and its
millilitre figures deliberately are not.

The profession already knows. Biller-Friedmann K, Bayerlein J, "[Visual estimation of
blood losses: Known high error rate - How can it be improved?]", *Die
Anaesthesiologie* 74(6):384-394, June 2025, DOI 10.1007/s00101-025-01517-6. The title
is the finding.

The failure is not ignorance. Measured alternatives exist - gravimetric weighing of
gauze, and haematocrit-based calculation - and both remain underused, because
measurement costs time and attention that the operating team does not have while
operating. A camera that is already in the room costs neither.

### 1.2 The safety step is skipped exactly where it is needed most

Aguilera M, et al. "Critical view of safety in laparoscopic cholecystectomy: a
nationwide video-based benchmark of resident-performed cases." *Surgical Endoscopy*,
3 August 2026. DOI 10.1007/s00464-026-13243-0. A nationwide review of 548 operative
videos at Pontificia Universidad Catolica de Chile.

> "CVS status was available for 513/548 recordings (93.6%), and CVS was achieved in
> 314/513 cases (61.2%)."

> "Achievement declined with complexity: OPRS 1, 66.5%; OPRS 2, 62.3%; OPRS 3, 56.3%;
> OPRS 4, 42.9%; and OPRS 5, 14.3% (p < 0.001)."

That gradient is the whole argument. The safety step that prevents the injury is
skipped most often in the hardest cases, and in the hardest tier it is achieved in
about one case in seven.

What it prevents: Yang S, et al., *Medicine (Baltimore)* 101(37):e30365, 16 September
2022, PMID 36123939, pooling 19 case-control studies over 41,044 patients, reports a
bile duct injury rate of **1.12%**. Mattson A, et al., *The Surgeon* 21(3):e133-e141,
June 2023, PMID 36243605, over 76,524 cases, reports **0.4%**.

**Published bile duct injury rates range from roughly 0.4% to 1.12% depending on the
population and the study design.** Both ends are given on purpose; picking the larger
one and presenting it as settled would be the easy and dishonest move.

The Yang paper also names the anatomical driver, which matters because it is exactly
what the laparoscope is looking at:

> "the anatomic variations of the gallbladder triangle (OR = 11.82, 95% CI:
> 6.32-22.09, P < .001)"

An eleven-fold odds ratio attached to how the anatomy looks in the triangle is a strong
argument that the decisive information is visual and is in the camera's field of view.

### 1.3 The bar a software intervention has to clear

WHO, "Safe surgery":

> "complications after inpatient operations occur in up to 25% of patients"

> "The Surgical Safety Checklist has been shown to reduce complications and mortality
> by over 30 percent. The Checklist is simple and can be completed in under 2 minutes"

The benchmark intervention in surgical safety is a two-minute paper checklist, and it
moved mortality by over 30%. That is a low, credible bar, and WHO set it. Scopewatch is
a checklist step that a camera can notice has not happened.

For scale, WHO's "Patient safety" fact sheet:

> "Around 1 in every 10 patients is harmed in health care and more than 3 million
> deaths occur annually due to unsafe care."

> "Above 50% of harm (1 in every 20 patients) is preventable"

### 1.4 What nobody has shown

**No deployed-system outcome trial could be found for any camera-based surgical safety
product.** If a judge asks whether this class of tool has been shown to save lives in
the field, the honest answer is that nobody has published that evidence. The evidence
above establishes that the measurement problem is real and that the safety step is
genuinely missed. It does not establish that measuring it changes an outcome, and this
report does not claim that it does.

---

## 2. Users

**The operating surgeon and the scrub team, after the case.** The primary use is
review: a timeline of the operation with the blood on the field measured rather than
recalled, the bleeding onset timestamped, and a record of what the team was asked and
what they answered. Everything Scopewatch produces is designed to be looked at on a
screen away from the sterile field.

**The surgical trainer.** The Chilean benchmark works because asynchronous video review
works. A tool that turns a 45-minute recording into a phase ribbon, a field trace and a
short event log makes that review affordable enough to do routinely rather than for
selected cases.

**The person who has to answer the checkpoint.** This is the only user who interacts
with Scopewatch during a case, and the interaction is one question with two answers,
one of which requires a written reason. The design constraint is that a checkpoint
which fires two minutes early is a checkpoint that gets dismissed out of habit, so the
approach window is deliberately short.

**Explicitly not a user: anyone making an intra-operative decision on Scopewatch's
number.** See section 8.

---

## 3. Architecture

Full diagrams in [architecture.md](architecture.md). In prose:

A clip is decimated and read frame by frame. Each frame passes four quality gates
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

### 4.2 Blood segmentation, chosen by experiment

Everything in an abdomen is red, so redness alone is not a discriminator. Six
candidates were implemented and scored against masks known by construction, with and
without a distractor - a patch of inflamed serosa, redder than the tissue around it and
no darker, which is exactly what a redness-only segmenter calls a haemorrhage.

The candidates: a fixed HSV hue range; Lab a*; YCrCb Cr; normalised redness
(R-G)/(R+G); Lab a* combined with L*; and normalised redness combined with a flattened
L*. The scores are in [evaluation.md](evaluation.md) and the winner is the last one.
Three findings came out of that sweep and each one changed the code.

**Otsu is the wrong tool when the target is a minority class.** Otsu assumes two
comparable populations. A frame with a large pool has blood on a few per cent of the
lit field, and a frame with no bleeding has none - so Otsu splits the *tissue*, along
the fat-against-vessel axis, and returns half the abdomen with complete confidence.
Every candidate now thresholds against the **tissue mode** instead: find the dominant
peak of the channel's histogram, measure its spread on the side the target class cannot
contaminate, and take what lies four sigma above it. That works when the target is a
tenth of a per cent of the field, and it returns nothing when the target is absent.

**CIE Lab's chroma axes compress dark colours.** A dark saturated red - which is what a
pool is - lands at an a* of about 165 while perfused tissue sits at 149 with a spread
of 5. Four sigma above the tissue mode is 167, and the pool falls on the wrong side of
it. On four of twenty-four sweep scenes that returned an **empty mask for a field a
quarter covered in blood**: a total miss, reported with confidence, on the largest
bleeds in the set. The normalised redness ratio has no such compression, because it is
a ratio: it is invariant both to the scope's automatic gain and to how dark the surface
is. The redness vote moved onto it.

**The scope's own lighting looks like blood.** A laparoscope's light source sits at the
tip, centimetres from the tissue, so the frame has a strong radial falloff and the
periphery is darker than the centre by a factor of two. The darkness vote cannot tell
that from a pool, and the result was a ring of false positives around every frame.
`blood.flatten_lightness` divides L* by a heavily blurred estimate of the illumination,
taken with the candidate blood region **excluded** - leave it in and a pool covering a
tenth of the field drags the local estimate down around itself, the flattened pool is
no darker than its surroundings, and a large haemorrhage is under-measured by a fifth.

One more, from the same sweep: a **surface vessel is redder and darker than the tissue
around it**, for the obvious reason, and so it passes both votes. It is not blood loss.
What separates them is shape: a pool has extent in two dimensions and a vessel has
extent in one. Each surviving component is measured on its own medial axis with
`distanceTransform`, and a component whose widest point is under nine pixels is a line,
not a pool. Using the *median* ridge width instead of the maximum discarded whole pools
that an instrument happened to cross, which produced a 100% error reported as zero
blood; the maximum does not have that failure.

Specular highlights from the light source are near-white and low-chroma, and they sit
inside pools as often as on tissue. Left in they punch holes in a pool and the area is
under-reported; classed as blood, a wet drape reads as haemorrhage. They are excluded
from both the mask and the field it is measured against, and the count is reported so
the exclusion is visible.

### 4.3 Scale, and its uncertainty

A laparoscopic instrument shaft is manufactured at a known outer diameter - 5 mm for
the common working instruments, with 3 mm paediatric and 10 mm devices also in the
catalogue. That makes every instrument in view a calibration target, and it is how
Scopewatch gets millimetres per pixel out of a monocular video with nothing added to
the theatre: no marker, no chessboard, no second camera.

The shaft's width is measured on its medial axis - `distanceTransform`, then the ridge,
then the median of twice the distance, with the ends trimmed because a grasper's jaws
flare and the port end is a partial cross-section. This is the same measurement
`visioncore.stroke_width_profile` performs for crack widths, and it carries the same
warning: filling a contour before measuring it measures the enclosed area, not the
stroke, and that is a two-orders-of-magnitude error that looks like a working number.

Two geometric decisions were needed and both are stated rather than hidden.

First, a component that fails the elongation test but is large and crosses the field
edge is **kept and flagged as merged**, because two instruments working on the same
structure touch, and the union of two crossed shafts is not elongated. Rejecting it
loses both, and with them the scale. The median of the medial-axis widths still lands
on the shaft width, because most of the ridge runs along a shaft; the wide-device cue
reads the 95th percentile instead, because when a clip applier crosses a grasper only
the upper tail of the width distribution sees it. Instrument *count* comes from the
number of separate places steel crosses into the field, not from a component count in
the middle, for the same reason.

Second, **the scale is isotropic and local.** It says how many millimetres a pixel
spans at that shaft's distance. It says nothing about the orientation of the surface
the blood is lying on. A pool on peritoneum tilted away from the camera projects to a
smaller area than it has, by cos(tilt), and multiplying pixels by an isotropic scale
therefore under-reports it. A single camera with no planar reference cannot recover
that tilt, so it is not estimated - it is bounded. Beyond about forty degrees a surgeon
repositions because they cannot see what they are doing either, so the upper end of
every area interval is widened by 1/cos(40 degrees) = 1.305. The lower end is not: tilt
can only make the true area larger than the projection, never smaller.

### 4.4 Area to volume, and the honesty it requires

Pixel area is not millilitres. Getting from one to the other needs a scale, which is
recovered above, and a depth, which a single camera cannot see.

Scopewatch does not pretend about the depth. The film thickness of pooled blood on
peritoneal or hepatic surface is an **assumption with a stated range of 1 to 3 mm**,
and every volume is the interval that range produces, never a point. A deliberately
wide three-fold span, because a three-fold span is the honest state of knowledge.

The area's own uncertainty is a function of the measurement, not a constant percentage,
and the sweep is what showed that. The error is not a fixed fraction: it is a roughly
constant *number of pixels* of false positive - surface vessels and inflamed serosa
that survive both votes - divided by however big the pool is. At seventy thousand
pixels that floor is under one per cent of the answer; at four thousand it is most of
it. So `blood.relative_area_sigma` combines a measured false-positive floor with a
residual shape error, and the scale's relative error enters squared because area is a
square. The result: [evaluation.md](evaluation.md) reports how often the printed
interval contains the truth.

The running total is the other place a tool like this usually overclaims. Blood on the
field at any instant is not blood lost: suction removes it and swabs absorb it, and
both leave the camera's view permanently. Scopewatch reports the **sum of the positive
increases in on-field volume**, labels it a lower bound everywhere it appears, and says
in the interface why. It is useful for comparing two halves of one case, or the same
operation done twice. It is not a transfusion decision and the report says so.

### 4.5 Bleeding onset

Two obvious approaches are both wrong. Thresholding the volume answers "when was there
a lot of blood", which is minutes later than the event and is the delay a surgeon
already has by eye. Thresholding the raw first difference confuses a camera pan with a
bleed, because a scope panning across an existing pool produces the same positive
slope.

So: a least-squares slope over a four-second **trailing** window - trailing because a
theatre instrument may not look into the future - in millilitres per minute, confirmed
by a one-sided CUSUM on the same series. Both must agree. Every candidate frame is
gated on a global motion estimate from `cv2.phaseCorrelate` on a 256-pixel Hanning
window, which costs well under a millisecond and answers the only question the pipeline
needs it to answer: did the whole field move.

The CUSUM's slack and decision interval are scaled from the series' own noise rather
than set in absolute millilitres, using the median absolute first difference. The
median, not the standard deviation, precisely because the change being hunted is in the
tail: a standard deviation computed over a series containing the bleed is inflated by
the bleed, and the detector then needs a bigger bleed to notice it.

The threshold itself had to be rethought once the physics was worked through. A
laparoscope at working distance sees roughly four to eight centimetres across; at a
2 mm film that whole field holds only a few millilitres, and everything beyond that has
gone to suction and was never on camera. An onset threshold of 2 ml/min, which is what
this was set to first, is a threshold the field can physically never reach, and the
detector simply never fired. The default is now 0.35 ml/min **of blood visible on the
field**, and the interface says which quantity that is.

The reported onset carries the window length as its uncertainty, because that is
genuinely how well a windowed estimator can localise a step.

### 4.6 Instruments, phase, and what the DNN channel really contributes

The instrument channel is classical: low-chroma, bright, elongated components that
cross into the lit field. It is the channel the measurement depends on, because it
supplies the scale.

**YOLOX-tiny runs through `cv2.dnn` on every tenth kept frame, and this report is
explicit about what it does and does not do.** The official weights are trained on
COCO, and COCO has no surgical instrument classes. It cannot name a Maryland dissector
and nothing in this product implies that it can; every detection it returns carries the
note "COCO class; not a surgical instrument taxonomy", and there is a test that fails if
that note is removed. What it genuinely contributes is a licence-clean, ONNX-only,
OpenCV-5 DNN path - `readNetFromCaffe` and `readNetFromDarknet` were removed in 5.x, so
ONNX is the only option and YOLOX's Apache-2.0 export is the natural choice over AGPL
Ultralytics weights - and a measured `cv2.dnn` latency on the new engine. A surgical
instrument detector would need CholecT50's triplet annotations, which sit behind a
registration form this entry has not completed. That is named as the next step rather
than papered over.

Phase inference is a transparent rule-based temporal model with hysteresis, not a
learned classifier, and that is a choice rather than a shortcut. A checkpoint that stops
a surgeon has to be explainable in one sentence at the moment it fires. "Two
instruments, sustained dissection for twenty-five seconds, and a ten-millimetre device
just entered the field" is a sentence. A softmax is not. What that buys in honesty it
costs in validated accuracy, and section 6 gives the number rather than hiding it.

### 4.7 Refusal is a result

Four gates, each producing a named refusal that reaches the interface, the run record
and this report:

| Code | Statistic | Operating point |
|---|---|---|
| `OUT_OF_FOCUS` | variance of the Laplacian, on an eroded core of the lit field | below 25 |
| `LENS_FOGGED` | dark channel prior, plus global contrast as a second vote | dark channel above 132 **and** contrast below 22 |
| `OCCLUDED` | largest achromatic flat or blacked-out region | above 55% of the lit field |
| `EXPOSURE_CLIPPED` | pixels at either end of the 8-bit range | above 34% |

Every operating point came from a sweep, and two of them moved as a result.

The **focus** gate is measured on an eroded core because the edge of the projected
circle is the hardest edge in a laparoscopic frame - a step from tissue to nothing -
and left in, it dominates the Laplacian's variance. A frame blurred with a nine-pixel
sigma measured 1337 against a threshold of 55: the gate was structurally incapable of
firing. More interestingly, the sweep changed what the gate is *for*. Defocus barely
moves the area error, because the segmentation is a colour decision over a compact
region and blurring a red pool leaves it red. What defocus moves is the **scale**,
because the shaft's medial-axis width spreads as its edges soften: -0.3% at sigma 0,
-3.1% at sigma 2, -13.2% at sigma 8. The scale enters the area squared, so a 13% scale
error is a 24% volume error. The threshold is set where the scale error stays under
about three per cent.

The **occlusion** gate's first version tested for a large flat low-gradient region and
rejected 39% of a perfectly measurable clip, because a settled pool of blood is exactly
that: large, flat and low-gradient. Calling the thing you are trying to measure an
occlusion is the worst failure a gate like this can have. What an actual occluder has
that a pool does not is the absence of colour - gauze, a swab, a glove and a lens cap
are all achromatic, and blood and tissue are not - so the test is now flat **and**
desaturated, or simply dark enough to be no image at all.

A fifth refusal, `NO_SCALE_REFERENCE`, fires when nothing of known size is in the
field. The area fraction is still reported, because it is a real, unitless, comparable
quantity. The millilitres are withheld, and the interface says what would fix it: bring
an instrument into view, or supply the scale directly.

---

## 5. AWS deployment

Region us-east-1, account <aws-account-id>, everything tagged `Project=opencv26`.

- **ECR** repository `opencv26/scopewatch`. The image carries
  `opencv-python-headless==5.0.0.93`, the YOLOX-tiny ONNX file with its sha256 checked
  at build time, and the bundled sample clip.
- **App Runner** service at 2 vCPU / 4 GB, always on, x86_64. HTTPS with a managed
  certificate and no load balancer.
- **S3** bucket `opencv26-artifacts-<aws-account-id>` under the `scopewatch/` prefix, for
  sample media and result artefacts.
- **CloudWatch Logs** for the application and service logs.

The endpoint works from a cold start with no local file: the sample clip is inside the
image and there is a button that runs it.

`infra/deploy.sh` is idempotent - it builds from the repository root, pushes, creates
or updates the service, and polls until it reports RUNNING. Costs, with the arithmetic
and its sources, are in [costs.md](costs.md).

Two deployment choices worth defending. **App Runner rather than Lambda**: a judging
window is two weeks of unattended availability, and a one-to-two gigabyte OpenCV
container's cold start is unmeasured. A judge who waits thirty seconds for a first
response has already formed a view. **x86_64 rather than Graviton**: App Runner exposes
no ARM option in its pricing, its FAQ, or its API parameters. The aarch64 OpenCV 5
wheel does ship Arm's KleidiCV HAL, so a real Graviton story is available on EC2 or
ECS; it is not available here, and this report says so rather than implying an Arm
deployment that does not exist.

---

## 6. Evaluation

Full method, numbers and plots: [evaluation.md](evaluation.md). The machine-readable
version is `docs/evaluation.json`, which the running service also serves at
`/api/evaluation` so the error bars sit next to the numbers they qualify.

**What was measured.** Synthetic operating fields generated by `scopewatch.synth`,
where every quantity the product claims to measure is set before the pixels exist: the
pool's area in pixels, the shaft's width in pixels, the millimetres per pixel, the film
depth, the frame the bleed starts on, and the phase at every instant. Seven
experiments: the colour-space trial, area error across three decades of pool size,
scale error, volume-interval coverage, refusal curves swept across blur, fog and
occlusion, onset timing on scripted cases with and without a bleed, and a phase
confusion matrix with the checkpoint's timing.

**What was not measured, and why.** There is no clinical video in this entry. The
published laparoscopic datasets that carry the labels Scopewatch would want -
Endoscapes for the critical view of safety, CholecT50 for instrument and action
triplets - are released under CC BY-NC-SA 4.0 behind registration forms that take days
to clear, and the request has not been completed. The README carries that as an open
item with the licence terms and their consequences.

**What that means for the claims.** The synthetic numbers are real evidence about the
estimator and no evidence at all about tissue. An area error measured against an area
we drew says the segmentation, the morphology and the arithmetic are right. It says
nothing about whether real peritoneum under a real xenon lamp separates from real
pooled blood the way the renderer's does. The evaluation document states that on its
first page, and validation on clinical video is named as the next step, not as
something already done.

---

## 7. Limitations

1. **No clinical video, no field trial, and no outcome evidence for this class of
   tool.** See 1.4 and section 6. This is the largest limitation and nothing in this
   entry compensates for it.
2. **Depth is an assumption.** Volume is area times a film thickness a single camera
   cannot see. The interval is honest about that and is correspondingly wide.
3. **Surface tilt is bounded, not measured.** A pool on a tilted surface is
   under-projected. The upper bound absorbs up to forty degrees; beyond that the number
   is wrong and nothing in the pipeline knows.
4. **The running total is a lower bound.** Suctioned and absorbed blood leaves the
   field and is never counted. It is labelled as a lower bound in the interface, the
   record and here.
5. **Small pools are not measurable.** The false-positive floor is a roughly constant
   number of pixels, so below a few thousand pixels the error swamps the measurement.
   The interval widens accordingly and the measurement is flagged unreliable rather
   than quietly reported.
6. **Phase inference is validated only on scripted synthetic sequences.** It is a
   transparent rule-based model, so it is auditable, but its accuracy on operative
   video is unknown.
7. **The DNN channel names no surgical instrument.** COCO has no such classes. It is a
   second opinion and a latency measurement, and the code says so in every record it
   produces.
8. **The safety view is declared, not detected.** Scopewatch does not score the three
   criteria of the critical view of safety. It notices that the phase suggests the
   irreversible step is near, and it asks. Scoring the criteria needs Endoscapes.
9. **Camera motion is a translation estimate.** `phaseCorrelate` answers "did the field
   move". A rotation or a zoom is not modelled, and a fast rotation could pass the gate.
10. **Per-process state.** A held checkpoint does not survive a service restart, by
    design: the honest state to come back in is "nothing was decided", not a checkpoint
    of unknown age that appears to have been reviewed.
11. **x86_64 only in the deployed service**, for the App Runner reason above.

---

## 8. Responsible use

**Scopewatch is not a medical device.** It has no regulatory clearance of any kind, it
has not been through a field trial, it has never been run on clinical video, and it is
not offered for intra-operative decision-making. It is a retrospective measurement and
training instrument, and where it asks a question during a case it asks it of a person
and records the answer.

**It takes no clinical action.** It measures, it asks, and it records what a person
decided. Every checkpoint is resolved by a named human. None expires, times out or
resolves itself. The service refuses an anonymous confirmation, and refuses a dismissal
that carries no reason; both refusals are tested. Feeding a held checkpoint a hundred
further frames leaves it held, and there is a test for that too.

**It refuses rather than guesses.** Four quality gates and a scale gate mean that a
fogged lens, a defocused scope, an occluded field or a frame with nothing of known size
in it produces a named refusal and no number. That behaviour is the feature. A tool
that reports through smoke is worse than one that stops.

**No identifiable people, anywhere.** The sample media are synthetic scenes drawn with
OpenCV primitives. There is no patient, no clinician, no face, and no real operative
footage in this repository. Nothing here performs face recognition or any other
biometric identification, and the pipeline has no code path that could.

**Data rights.** No third-party dataset is redistributed here. The one third-party
artefact is the YOLOX-tiny ONNX file, Apache-2.0 from Megvii, whose checksum is
recorded and verified at build time. The surgical datasets named in the README are
named as an open access request, not used. No AGPL-licensed model or code is present:
AGPL-3.0 section 13 extends copyleft to network use, which a hosted demo endpoint
triggers, and that risk is not worth taking.

**Where this could do harm, and what stops it.** The realistic failure is a clinician
trusting a millilitre figure that is wrong - from an unrecovered surface tilt, from a
film depth outside the assumed range, or from blood the camera never saw. Four things
work against it: the number is always an interval and never a point; the interval
widens automatically as the measurement gets less reliable; the running total is
labelled a lower bound everywhere it appears; and the interface carries a persistent,
non-dismissible line saying this is retrospective measurement and not intra-operative
guidance. None of those is sufficient. Clinical validation is, and it has not been
done.
