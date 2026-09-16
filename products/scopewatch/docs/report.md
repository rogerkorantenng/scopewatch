# Scopewatch: measuring the laparoscopic operating field

Technical report, OpenCV AI Competition 2026.

---

## 0. What real footage showed, and what changed

Scopewatch was designed and evaluated on synthetic laparoscopic scenes, where every
number it reported could be checked and was right. It was then run on sixteen openly
licensed real surgical clips from Wikimedia Commons and Zenodo, locally and on the live
service, with identical results. On real video it failed in five ways:

1. **Blood.** A clearly bleeding field (WSES ulcer repair) read 0.00 ml on 555 of 561
   frames. A nearly bloodless one (Barroso hernia repair) read up to 9.79 ml, all of it
   shadowed tissue at the rim of the scope's circle. On the Kavalakat omentectomy the
   inside of a port sleeve was called blood.
2. **Onset** fired on none of the sixteen clips, and on three the reason said a slope of
   17.87, 19.13 or 98.11 ml/min "never reached 0.35 ml/min", which was false.
3. **The checkpoint** was held on five clips with its critical approach starting 25.8 to
   27.8 s in: the 20-second dwell plus start-up, whatever was in the picture.
4. **Scale** was missing on five clips with shafts in plain view, and where present
   implied a field 92 to 205 mm wide.
5. **Gates**: an open operation was measured as if laparoscopic.

How each was found, frame by frame, and what was done about it:

| Defect | Root cause, as measured | Change | Result on real footage |
|---|---|---|---|
| Blood missed on a bleeding field | "Redder than the tissue mode and darker than its surroundings": with a lot of blood in view neither vote holds | Chroma per unit lightness, red hue, saturation relative to the scene; darkness is not used as evidence | Held-out clips: pixel precision 0% to 13.0%, recall 0% to 10.7% |
| Rim shadow and port sleeve called blood | Vignetting and shadow are "darker than their surroundings" | The rim is removed, badly lit regions are not classified | Barroso peaks at 0.0% of the field; sleeve crop 11% to 1.4% |
| False onset reason | The message ignored two of the five gates. The high slopes came from mis-segmentation and from unscaled frames entering the series as 0 ml | Reason counts every gate; gaps hold the last value; onset runs on the field share | Still no onset on any clip, now with the true reason: camera motion and instrument changes |
| Checkpoint on a timer | The width cue compared a p95 with a median of p50s and was true on 70 to 89% of frames before the dwell armed it | Same statistic on both sides, must persist, dwell only arms it; **automatic checkpoint off by default** | Not on a timer, but still fooled by a grasper near the lens, hence demoted |
| Scale missing / 2x coarse | Pixel floors set at 960 px; the steel mask is the lit stripe of the shaft, a median 2.2x narrower than the shaft | Floors scale with the frame; width measured edge to edge | Implied field 46 to 108 mm, but the scale varies 29 to 61% within a clip, so the volume is withheld on all 16 |
| Open surgery accepted | No domain gate | `OUT_OF_DOMAIN` on cool-hue drapes and large near-white objects in a saturated field | Gupta refused; Kaplan S6's draped tail refused; about 18 laparoscopic frames wrongly refused |

**What the product outputs now follows from that table.** The headline is the share of
the visible field segmented as blood and its rate of change, shown with the precision
and recall measured on held-out real frames. A volume in millilitres appears only when
the instrument scale is present and steady, labelled as never validated on real
footage, and otherwise the row says `CANNOT_MEASURE` with the reason. On all sixteen
real clips it says `CANNOT_MEASURE`.

**There is no ground-truth blood volume for any real clip, and there never will be from
these sources.** Nobody weighed the swabs. So no millilitre figure in this product has
been checked against reality, and this report does not claim an accuracy in
millilitres on real footage. What real footage can check, and what
[evaluation.md](evaluation.md) Part A reports, is whether blood pixels are blood
(against 64 hand-labelled frames), whether refusals fire, whether onset fires and why
not, and whether the checkpoint depends on the picture. The sections below describe the
design; where real footage changed it, they say so.

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

### 4.2 Blood segmentation, chosen by experiment

Everything in an abdomen is red, so redness alone is not a discriminator. Six
candidates were implemented and scored against masks known by construction, with and
without a distractor - a patch of inflamed serosa, redder than the tissue around it and
no darker, which is exactly what a redness-only segmenter calls a haemorrhage.

The candidates: a fixed HSV hue range; Lab a*; YCrCb Cr; normalised redness
(R-G)/(R+G); Lab a* combined with L*; and normalised redness combined with a flattened
L*. The scores are in [evaluation.md](evaluation.md) and the synthetic winner is the
last one. Three findings came out of that sweep and each one changed the code.

**Then real footage overturned the choice.** The synthetic winner, `ratio_dark`, scored
0% precision and 0% recall on held-out real clips. A seventh candidate, `chroma_scene`,
now ships, chosen on the dev half of hand-labelled real frames. It asks for chroma per
unit lightness (blood is deeply coloured for how light it is; shadow is dark and grey;
pink tissue is coloured but light), a red Lab hue between 8 and 50 degrees, and chroma
per lightness at least 1.35 times the scene's median, because under a warm light a whole
field of bowel can pass the absolute tests. It never uses darkness as evidence. It drops
a rim of 2% of the frame and anything lit below 35% of the field's median, and fills
specular highlights back in where they sit on a candidate region. On synthetic scenes it
is worse than the old winner (Dice 0.833 against 0.994 with the distractor; Part B of
the evaluation). On real held-out clips it is better and still poor. The findings below are about the synthetic
sweep, and they stand as a record of how the original decision was made.

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

**Real footage changed this measurement.** On a wet steel shaft under a scope's light
only the stripe facing the light passes the "bright and low saturation" steel test, so
the medial-axis width was half the shaft: a median 2.2 times too narrow on nine real
shafts, which is why the field of view came out about twice too wide. The scale now
comes from an edge-to-edge width read off saturation profiles across the shaft axis,
measured near where each instrument enters the field so that crossed instruments are
still apart. The medial-axis width described next is still used for the instrument count
and the phase features. The pixel floors are scaled with the frame, because a 900-pixel
area floor set on 960-pixel frames threw away every shaft on the 320 x 240 clips. And the
scale is gated over the whole case: see 4.4.

The shaft's width was originally measured on its medial axis - `distanceTransform`, then the ridge,
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

**On real footage the volume is withheld.** A shaft's apparent width moves with its
distance from the lens, and the blood lies at yet another distance, so the per-frame
scale on real clips varies by 29 to 61% (robust coefficient of variation). A volume is
now computed only when at least 25% of measurable frames and at least 50 frames carry a
shaft scale and that variation is under 25%, at the case's median scale. Otherwise the
record carries `CANNOT_MEASURE` with `NO_SCALE_REFERENCE` or `SCALE_INCONSISTENT`. No real
clip passes. The arithmetic below is unchanged and applies on synthetic scenes and
whenever an operator supplies the scale.

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

**What changed after real footage.** The series is now the blood-covered share of the
field, in percentage points, with a default threshold of 8 points a minute, because the
millilitre series needs a scale real footage does not give. Frames that cannot be
measured hold the last measured value instead of entering as zero; the zeros had turned
every refusal gap into a fall and a rise, and all 32 over-threshold frames on the
Kavalakat clip had one inside their window. When no onset is declared, the reason now
counts, for every frame whose rate crossed the threshold, the gate that stopped it:
refused frame, camera motion, too-small blood area, an instrument entering or leaving,
or no CUSUM confirmation. On the sixteen real clips it never fires, and the reason says
why: every crossing happened while the camera or an instrument was moving. The design
below is otherwise unchanged; the millilitre threshold it discusses still applies when a
volume series exists.

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

**The automatic checkpoint is off by default, and here is why.** On real clips the
checkpoint was held at the same 26 to 28 s on five clips. Probing every frame showed the
wide-device cue (widest shaft's 95th-percentile mask width against a running median of
50th percentiles) was already true on 70 to 89% of frames before the 20-second dwell
armed it, so the dwell was the trigger. The cue now compares edge widths with edge
widths, must hold for 1.5 s, and the dwell can only arm it; a test pins that dissection
alone never reaches the critical approach. With that, checkpoints on real clips moved to
43, 85 and 88 s on three Kaplan clips, driven by the picture. But in at least one of
them the "wide device" is a black grasper nearer the lens: instrument width cannot tell a
clip applier from a closer grasper. So the checkpoint mechanism stays (hold, confirm,
dismiss with a reason, named person), the automatic trigger is an experimental option,
and the interface says so.

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

Another refusal, `OUT_OF_DOMAIN`, came from real footage: an open cholecystectomy had been
measured as if it were laparoscopic. It fires when drapes or gowns (a cool hue over 45%
of the field) or large near-white objects such as gloves (over 8% of the field, in a
field whose remaining saturation is at least 120) are in view, and a clip is refused
when a quarter of its frames are. It refused the open clip and the draped tail of a
laparoscopic one, and about 18 laparoscopic frames it should not have. It rests on one
open-surgery clip. The fog gate did not fire on the real ADM_LSIR aerosol frames, and
should not have: those are sparse bright streaks over a clear field (dark channel 55 to
92, contrast 32 to 37), not haze. No real clip had haze, so the fog gate is still
validated on synthetic haze only.

`NO_SCALE_REFERENCE` now withholds the volume, not the frame, when nothing of known size is in the
field. The area fraction is still reported, because it is a real, unitless, comparable
quantity. The millilitres are withheld, and the interface says what would fix it: bring
an instrument into view, or supply the scale directly.

---

## 5. AWS deployment

Account <aws-account-id>, region **eu-central-1**, everything tagged `Project=opencv26`.

The region is a deviation from the plan and worth stating rather than burying. App
Runner on this account is capped at two services per region, and at deploy time all
three US regions were at that cap with other projects, so `CreateService` returned
`InvalidRequestException: Account <aws-account-id> is restricted and can support only two
App Runner services per region at the moment`. eu-central-1 had both slots free. For a
US judge this costs about 100 ms of round-trip latency and nothing else, and the
deployment script takes its region from the environment, so moving back is one command
if a US slot frees up.

- **ECR** repository `opencv26/scopewatch`. The image carries
  `opencv-python-headless==5.0.0.93`, the YOLOX-tiny ONNX file with its sha256 checked
  at build time, and the bundled sample clip.
- **App Runner** service at 2 vCPU / 4 GB, always on, x86_64. HTTPS with a managed
  certificate and no load balancer.
- **S3** bucket `opencv26-artifacts-<aws-account-id>` under the `scopewatch/` prefix, for
  sample media and result artefacts.
- **CloudWatch Logs** for the application and service logs.

**Live at <https://s3vrzphtvv.eu-central-1.awsapprunner.com>**, `/version` git_sha `06a2f28`. Repository: <https://github.com/rogerkorantenng/scopewatch>.

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
versions are `docs/evaluation.json` and `docs/real-evaluation.json`; the running
service serves the first, which includes the second, at `/api/evaluation`.

**Part A, real footage.** Sixteen openly licensed clips, run before and after. Blood is
scored against polygons drawn on 64 fixed frames by a labeller who never saw the
product's output, split by clip into dev (thresholds chosen) and test (not). Headline:

| Held-out real clips | Before | After |
|---|---|---|
| Blood pixel precision | 0.0% | 13.0% |
| Blood pixel recall | 0.0% | 10.7% |
| Clips showing a volume | 11 of 16 | 0 of 16 (`CANNOT_MEASURE`) |
| Onset fired | 0 of 16, reason false on 3 | 0 of 16, reason names the gates |
| Checkpoint held | 6 of 16, five of them on the dwell timer | 0 by default (off, experimental); 3 of 16 if switched on |
| Open-surgery clip refused | no | yes |

On the dev clips, where the thresholds were chosen, precision and recall are 61% and
50%. The distance between that and 13% and 11% is the most important thing Part A says.

**Part B, synthetic scenes.** Area, scale, volume-interval coverage, refusal sweeps,
onset timing, phase confusion and checkpoint timing, on scenes where every quantity is
set before the pixels exist. Evidence about the arithmetic, none about tissue. The
real-footage changes made these numbers worse, and Part B says so: pools under 0.4% of
the field are dropped, the volume interval contains the truth in 39 of 48 scenes
(81%) instead of 48 of 48, and per-frame time at 960 x 540 went from 38.8 ms to
142.9 ms (3.7×, measured while other jobs shared the machine).

**What was not measured.** No real clip has a known blood volume, so no volume accuracy
on real footage exists or is claimed. No clinical dataset with expert labels was used;
the labelled datasets (Endoscapes, CholecT50) are CC BY-NC-SA behind registration forms,
and the README carries that as an open item.

---

## 7. Limitations

1. **No ground-truth blood volume on any real footage, no field trial, and no outcome
   evidence for this class of tool.** The real-footage evaluation is 16 public clips and
   64 frames labelled by one non-surgeon. See 1.4 and section 6.
2. **Blood versus red tissue.** On held-out real clips the segmentation's pixel precision
   is 13% and recall 11%. The blood-covered share includes red tissue, and its peaks
   are mostly camera swings toward red tissue.
3. **Onset on a moving camera.** It has never fired on real footage. There is no image
   stabilisation, and a still four-second window is rare in a working field.
4. **Scale.** Missing on black-coated shafts and shafts merged with pale tissue;
   inconsistent everywhere else, so no real clip gets a volume.
5. **Depth is an assumption.** Volume is area times a film thickness a single camera
   cannot see. The interval is honest about that and is correspondingly wide.
6. **Surface tilt is bounded, not measured.** A pool on a tilted surface is
   under-projected. The upper bound absorbs up to forty degrees; beyond that the number
   is wrong and nothing in the pipeline knows.
7. **The running total is a lower bound.** Suctioned and absorbed blood leaves the
   field and is never counted. It is labelled as a lower bound in the interface, the
   record and here.
8. **Small pools are dropped.** Blood covering under 0.4% of the field is not reported,
   because on real dev frames components that small were mostly red tissue. On
   synthetic scenes that drops every 400 px pool (0.2% of the field) entirely, mean
   area error moved from -0.98% to -19.9%, and volume-interval coverage fell from 48 of
   48 scenes to 39 of 48 (81%); the nine misses are the dropped small pools.
9. **Phase inference is validated only on scripted synthetic sequences**, and its
   width cue is fooled on real video by an instrument's distance from the lens. The
   automatic checkpoint that depends on it is off by default.
10. **The DNN channel names no surgical instrument.** COCO has no such classes. It is a
   second opinion and a latency measurement, and the code says so in every record it
   produces.
11. **The safety view is declared, not detected.** Scopewatch does not score the three
   criteria of the critical view of safety. It notices that the phase suggests the
   irreversible step is near, and it asks. Scoring the criteria needs Endoscapes.
12. **Camera motion is a translation estimate.** `phaseCorrelate` answers "did the field
   move". A rotation or a zoom is not modelled, and a fast rotation could pass the gate.
13. **Per-process state.** A held checkpoint does not survive a service restart, by
    design: the honest state to come back in is "nothing was decided", not a checkpoint
    of unknown age that appears to have been reviewed.
14. **The out-of-domain gate rests on one open-surgery clip**, and wrongly refuses a
    few laparoscopic frames with large glare or gauze.
15. **x86_64 only in the deployed service**, for the App Runner reason above.

---

## 8. Responsible use

**Scopewatch is not a medical device.** It has no regulatory clearance of any kind, it
has not been through a field trial, it has been run only on sixteen public surgical
videos with no known blood volumes, and it is not offered for intra-operative
decision-making. It is a retrospective measurement and
training instrument, and where it asks a question during a case it asks it of a person
and records the answer.

**It takes no clinical action.** It measures, it asks, and it records what a person
decided. Every checkpoint is resolved by a named human. None expires, times out or
resolves itself. The service refuses an anonymous confirmation, and refuses a dismissal
that carries no reason; both refusals are tested. Feeding a held checkpoint a hundred
further frames leaves it held, and there is a test for that too.

**It refuses rather than guesses.** Five quality gates and a scale gate mean that a
fogged lens, a defocused scope, an occluded field, clipped exposure, video that is not
laparoscopic, or a frame with nothing of known size in it produces a named refusal and no number. That behaviour is the feature. A tool
that reports through smoke is worse than one that stops.

**No identifiable people, anywhere.** The sample media are synthetic scenes drawn with
OpenCV primitives. The only real operative material in this repository is six small
crops used as regression tests (`tests/fixtures/real/`, each credited, CC BY 4.0 or
CC BY 2.0) and polygon labels drawn over frames of the sixteen public clips; no clip is
stored. None shows a face, a name or a record number. Nothing here performs face recognition or any other
biometric identification, and the pipeline has no code path that could.

**Data rights.** No third-party dataset is redistributed here. The one third-party
artefact is the YOLOX-tiny ONNX file, Apache-2.0 from Megvii, whose checksum is
recorded and verified at build time. The surgical datasets named in the README are
named as an open access request, not used. No AGPL-licensed model or code is present:
AGPL-3.0 section 13 extends copyleft to network use, which a hosted demo endpoint
triggers, and that risk is not worth taking.

**Where this could do harm, and what stops it.** Real footage showed this happening:
a bleeding field read as 0.00 ml and a bloodless one as 9.79 ml. The volume is now
withheld unless its scale holds steady, and on real footage it has always been
withheld. The realistic failure is a clinician trusting a millilitre figure that is wrong - from an unrecovered surface tilt, from a
film depth outside the assumed range, or from blood the camera never saw. Four things
work against it: the number is always an interval and never a point; the interval
widens automatically as the measurement gets less reliable; the running total is
labelled a lower bound everywhere it appears; and the interface carries a persistent,
non-dismissible line saying this is retrospective measurement and not intra-operative
guidance. None of those is sufficient. Clinical validation is, and it has not been
done.
