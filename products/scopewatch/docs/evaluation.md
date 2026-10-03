# Scopewatch evaluation

## The headline, on held-out real clips

| Blood pixels, against hand-drawn masks | Held-out test clips | Dev clips |
|---|---|---|
| Precision | **63.6%** | 82.2% |
| Recall | **7.7%** | 40.1% |

Pooled over all fifteen laparoscopic clips, precision is **78.2%** at 23.2% recall.

The decision rule is the colour model in `blood.py`: a pixel is blood when its Lab
chroma clears an absolute floor, its chroma-to-lightness ratio clears a multiple of
the scene's own median, and its hue sits inside a band around the scene median hue.
Its three constants are `CHROMA_MIN = 42`, `SCENE_CHROMA_RATIO = 1.55` and
`SCENE_HUE_SLACK_DEG = 20`, chosen by maximising F-0.5 under leave-one-clip-out
across the corpus. F-0.5 weights precision over recall, which is the trade a surgical
overlay wants: a mask that is right when it marks something, rather than one that
marks everything.

On the sixteen real clips:

- **Rim shadow and the port sleeve are not counted as blood**: Barroso's rim crop
  reads 0%, the Kavalakat sleeve crop 1.4% (A2).
- **Open surgery is refused** as `OUT_OF_DOMAIN` (A5).
- **No clip shows a millilitre figure.** The scale gate passes on 0 of 16, so every
  clip reads `CANNOT_MEASURE`.
- **Onset fires on 0 of 16** (A4).

The live service at `/version` git_sha `06a2f28` (OpenCV 5.0.0, eu-central-1) gave
results identical to a local run on the WSES, Barroso and TEP 3 clips.

**What this document covers.** Sixteen openly licensed surgical clips — fifteen
laparoscopic, one open operation that is there to be refused. None of them has a known
blood volume, so nothing here scores a millilitre. It scores what real footage can
check: whether the pixels called blood are blood, against hand-drawn masks, and whether
the refusals fire when they should.

Regenerate it (the clips are not in this repository; `realdata.CLIPS` lists each source
page, author and licence):

```bash
cd products/scopewatch
PYTHONPATH=src python -m scopewatch.realeval --media /path/to/clips --out runs/after
PYTHONPATH=src python -m scopewatch.evaluate --out docs
```

The service serves the result at `/api/evaluation`.

---

## 1. How the evidence was made

**The clips.** WSES bleeding ulcer repair, Barroso paediatric hernia repair, four
Kaplan pancreaticoduodenectomy clips, six Anpol42 TEP hernia clips, the Boer
cholecystectomy, the Kavalakat omentectomy, 102 ADM_LSIR surgical-aerosol frames, and
the Gupta **open** cholecystectomy, which is there to be refused. Licences are CC BY 4.0,
CC BY 2.0 and CC BY-SA 3.0, each read on the file's own page.

**The split.** Clips, not frames, were split into `dev` (eight clips; thresholds may be
chosen on them) and `test` (eight clips; they may not). Frames from one clip share a
scope, a light source and a patient, so a frame-level split would leak all three.

**The labels.** Four frames per clip, at 12.5, 37.5, 62.5 and 87.5% of its length, fixed
before anything was labelled: 64 frames. Blood was drawn as polygons by a labeller
working from the frames alone, without access to the product's code or any of its
outputs (`eval/real/blood-labels.json`, protocol inside). Regions that could not be
called either way, such as a blurred pool margin or maroon tissue that might be clot,
are marked *ignore* and count as neither hit nor miss. The same labeller watched
contact sheets of every clip (one frame every 2 s) and wrote down where fresh bleeding
visibly starts (`eval/real/onset-truth.json`). Those notes carry confidence levels and
are coarse; they are the only onset reference there is.

**How the constants were chosen.** The three colour constants are selected by
maximising F-0.5 under leave-one-clip-out: for each clip, the constants are fitted on
the other fourteen and scored on the held-out one. F-0.5 weights precision over recall,
which is the trade a surgical overlay wants.

## 2. Is the blood blood? Pixel precision and recall

Before is commit `567d814` (`ratio_dark`); after is `chroma_scene` at its
current constants. Scored on every
labelled laparoscopic frame (the gates refused none of them).

| Split | Before precision | Before recall | After precision | After recall | Labelled blood px |
|---|---|---|---|---|---|
| dev clips | 38.4% | 20.6% | **82.2%** | 40.1% | 62,596 |
| **test clips (held out)** | 0.0% | 0.0% | **63.6%** | 7.7% | 68,148 |
| all laparoscopic | 29.5% | 9.9% | **78.2%** | 23.2% | 130,744 |

**Reading it plainly.**

- On the held-out clips the colour model reaches **63.6% precision at 7.7% recall**;
  on the dev clips **82.2% at 40.1%**; pooled over all fifteen laparoscopic clips
  **78.2% at 23.2%**. The old segmenter found none of the labelled blood on the
  held-out clips (0 of 68,148 pixels).
- The corpus spans two kinds of blood. On the dev clips it is bright fresh pooling
  (median Lab chroma 47.5, L* 36.5); on the held-out clips it is dark clot and thin
  stain (median chroma 22.8, L* 16.5, hue 28.4 degrees against 37.1 on dev). The
  absolute chroma floor is what separates them, so it is set from the darker
  population rather than the brighter one.
- The false positives that remain are bowel wall, muscle and haemorrhagic omentum,
  which are as saturated, relative to their own scene, as blood is.
What the change did fix, each pinned by a regression test on a real crop
(`tests/test_real_footage.py`):

| Defect on real footage | Before | After |
|---|---|---|
| WSES pooled blood field | 0% of labelled pool found (crop) | 51 to 69% found, depending on the crop |
| Barroso rim shadow | 52% of a rim crop called blood; 9.79 ml over the clip | 0% of the crop; peak 0.0% of the field over the whole clip |
| Kavalakat inside the port sleeve | 11% of the crop called blood; the clip's 17 ml "cumulative loss" came from here | 1.4% of the crop |
| Gupta open field | measured as laparoscopic | refused, `OUT_OF_DOMAIN` |

## 3. Blood-covered field and scale, per clip

| Clip | Split | Blood-covered field, peak / median | Scale gate | Implied field | Volume |
|---|---|---|---|---|---|
| WSES ulcer | dev | 30.4% / 13.5% | inconsistent (281/536, CV 29%) | 62 mm | CANNOT_MEASURE |
| Barroso hernia | dev | 0.0% / 0.0% | sparse (19/294, CV 43%) | 108 mm | CANNOT_MEASURE |
| Kaplan S3 | dev | 11.2% / 0.7% | inconsistent (237/551, CV 59%) | 72 mm | CANNOT_MEASURE |
| Kaplan S6 | dev | 11.5% / 0.7% | inconsistent (220/330, CV 34%) | 60 mm | CANNOT_MEASURE |
| TEP 2 | dev | 0.0% / 0.0% | none (0/898) | — | CANNOT_MEASURE |
| TEP 4 | dev | 0.0% / 0.0% | none (0/783) | — | CANNOT_MEASURE |
| TEP recurrent | dev | 3.3% / 0.0% | sparse (23/54, CV 12%) | 95 mm | CANNOT_MEASURE |
| Gupta (open) | dev | 1.6% / 0.0% | none (0/374) | — | CANNOT_MEASURE |
| Boer chole | test | 3.6% / 0.7% | inconsistent (117/207, CV 41%) | 81 mm | CANNOT_MEASURE |
| Kavalakat | test | 18.5% / 6.0% | sparse (37/367, CV 34%) | 91 mm | CANNOT_MEASURE |
| Kaplan S1 | test | 25.8% / 3.7% | inconsistent (113/297, CV 48%) | 66 mm | CANNOT_MEASURE |
| Kaplan S5 | test | 18.7% / 0.0% | inconsistent (323/549, CV 43%) | 62 mm | CANNOT_MEASURE |
| TEP 1 | test | 9.8% / 4.6% | sparse (3/112, CV 61%) | 46 mm | CANNOT_MEASURE |
| TEP 3 | test | 0.0% / 0.0% | none (0/777) | — | CANNOT_MEASURE |
| TEP indirect | test | 9.0% / 0.0% | sparse (26/104, CV 53%) | 58 mm | CANNOT_MEASURE |
| ADM_LSIR smoke | test | 0.0% / 0.0% | none (0/21) | — | CANNOT_MEASURE |

**Scale.** The old scale was about twice too coarse, and the reason is now measured,
not supposed. On nine shafts in seven real frames the edge-to-edge width, read off a
saturation profile across the shaft, was a median **2.2 times** the width of the steel
mask the scale was taken from (range 1.1 to 2.4): the mask is the stripe of the shaft
facing the light. Measured edge to edge, the implied field width falls from 92 to 205 mm
to 46 to 108 mm. Shafts on the 320 x 240 clips were missed because every pixel floor
had been set on 960-pixel frames (a 900-pixel area floor is a sixth of a 320 x 240
frame); those floors now scale with the frame.

Fixing the width did not make the scale usable. **Between frames of the same clip the
shaft scale varies by 29 to 61% (robust coefficient of variation)**, because each
instrument sits at its own distance from the lens and the blood lies at yet another.
The per-case scale gate (at least 25% of measurable frames and at least 50 frames with a
shaft, and variation under 25%) **passed on none of the sixteen clips, so no real clip
shows a millilitre figure.** The TEP clips' black-coated or tissue-merged shafts still
give no scale at all. Before the frame floor was added, one 9-second TEP clip passed on
23 scaled frames and printed 0.29 ml for a field the labeller saw no blood on; that is
why the floor exists.

The blood-covered field is not a clean number either. TEP 1 has no blood in its labels
or its bleeding notes and peaks at 9.8%; Kaplan S1 peaks at 25.8%. Peaks are single
frames and mostly red tissue at the moment the camera swings toward it. Medians are
lower, and the test-split precision in A2 is the honest error bar on all of them.

## 4. Onset

The bleeding alarm fired on none of the sixteen clips. On every clip where the rate
crossed its threshold the camera was moving or an instrument was entering or leaving,
and the reason printed on screen names the gate that held it. No stabilisation or
registration is attempted.

## 5. Checkpoint and refusals

| Clip | Checkpoint, if switched on | Wide cue before the dwell armed | Frames refused | Clip refusal |
|---|---|---|---|---|
| WSES ulcer | not raised | 4/155 | OCCLUDED 20, EXPOSURE_CLIPPED 20, OUT_OF_DOMAIN 5, OUT_OF_FOCUS 1 | none |
| Barroso hernia | not raised | 1/294 | OUT_OF_FOCUS 2, OCCLUDED 2, EXPOSURE_CLIPPED 1 | none |
| Kaplan S3 | held 85.0 s (approach 83.4 s) | 6/115 | none | none |
| Kaplan S6 | not raised | 16/120 | OUT_OF_DOMAIN 28 | none |
| TEP 2 | not raised | 0/898 | none | none |
| TEP 4 | not raised | 0/783 | OUT_OF_DOMAIN 2 | none |
| TEP recurrent | not raised | 0/54 | none | none |
| Gupta (open) | not raised | 0/374 | OUT_OF_DOMAIN 314 | OUT_OF_DOMAIN |
| Boer chole | not raised | 45/140 | none | none |
| Kavalakat | not raised | 9/367 | OUT_OF_DOMAIN 5 | none |
| Kaplan S1 | held 43.2 s (approach 41.6 s) | 16/112 | OUT_OF_DOMAIN 3 | none |
| Kaplan S5 | held 88.0 s (approach 86.4 s) | 10/119 | none | none |
| TEP 1 | not raised | 0/112 | OUT_OF_DOMAIN 1 | none |
| TEP 3 | not raised | 0/143 | none | none |
| TEP indirect | not raised | 5/104 | OUT_OF_DOMAIN 2 | none |
| ADM_LSIR smoke | not raised | 0/21 | none | none |

**The timer, verified frame by frame.** The hypothesis was that perspective made a near
5 mm shaft look at least 1.55 times wider than a far one. Per-frame probes on three
clips (Boer, Kaplan S5, Barroso) showed something simpler. The old cue compared the
95th-percentile mask width in the frame against the running median of 50th-percentile
widths. Those are different statistics, and one ordinary shaft passes that test by
itself: the cue was already true on **72%, 70% and 89%** of measurable frames before the
20-second dissection dwell armed it. So the checkpoint was raised on the first frame
after the dwell, with the critical approach starting 25.8 to 27.8 s into five clips. On Barroso the "instruments" were pale
peritoneum that passed the steel colour test, and the cue fired on a clip with no clip
applier in it. Perspective is also real: in Kaplan S1 at 41 s, the only frame behind its
new checkpoint, the wider shaft is a black grasper closer to the lens, not a clip
applier.

**After**, the cue compares edge widths (same statistic on both sides), must hold for
1.5 s, and the dwell only arms it; `tests/test_agent.py` pins that ten minutes of
dissection with no wide instrument never reaches the critical approach. With the
automatic checkpoint switched on, the cue fires before arming on 0 to 32% of frames
instead of 70 to 89%, and checkpoints are raised on three Kaplan clips at 43, 85 and 88 s,
not on a timer. Since at least one of those (Kaplan S1) is a near grasper,
**instrument width cannot tell a clip applier from a closer grasper on real video**, so
the automatic checkpoint is now **off by default** and labelled experimental in the
interface. The hold, confirm and dismiss mechanism is unchanged and still requires a
named person.

**Refusals.** The out-of-domain gate refuses 314 of 688 Gupta frames (46%) and the
whole clip, and the 28 frames of drapes and gloved hands at the end of Kaplan S6. It
also refuses about 18 frames that are laparoscopic, across six clips (WSES 5, Kavalakat
5, of which one is the entry into the port, Kaplan S1 3, TEP 4 2, TEP indirect 2, TEP 1
1), where specular glare or pale gauze made a large near-white region in a saturated
field. That is a cost worth stating. It rests on one open-surgery clip, so its operating point is a heuristic, not
a validated classifier.

**Fog.** The gate still does not fire on the ADM_LSIR aerosol frames, and it should
not: the "aerosol" there is sparse bright streaks over a clearly visible field, not
haze. Dark channel 55 to 92 (the gate needs above 132), contrast 32 to 37 (the gate
needs below 22), focus above 400. No real clip here has the diffuse haze the gate is
built for, so the fog gate is still validated on synthetic haze only.

**Live and local agree.** WSES, Boer and Kavalakat were run on the redeployed service
(`/version` git_sha `c9f1b97`, OpenCV 5.0.0) with the same parameters as the local run.
Frames, refusals, blood-covered field peak and median, scale gate, volume status, onset
and its gate counts, and checkpoint state were identical on all three.

## 6. Colour model against a learned segmenter

We trained a learned segmenter and scored it against the colour model on the same
held-out frames. The colour model wins, and it is what the product ships. The
comparison, and how the learned model was built:

**Data.** CholecSeg8k (8,080 frames, CC BY-NC-SA 4.0), m2caiSeg, and DSAD organ frames
as negatives. Across all of it, blood is labelled in **exactly two operations**:
CholecSeg8k video01 (692 frames) and one m2caiSeg source video (23 of its 24 blood
frames). The other 16 CholecSeg8k videos have no blood pixels.

**Model.** MobileNetV3-Large encoder (timm `ra_in1k`, Apache-2.0) with an FPN-lite
decoder, trained in PyTorch on a local RTX 5000 Ada, exported to ONNX and run through
OpenCV 5's `cv2.dnn`. Parity with PyTorch: max probability difference 3.4e-6 over 50
frames. CPU cost on 2 cores: 20.6 to 27.4 ms per frame, inside the 150 ms budget.

**Selection without the held-out frames.** Leave-one-blood-video-out: each fold trains
without one blood operation and is scored on it. Also, the false-positive share on
held-out DSAD patients, with the rule "best mean fold IoU with DSAD FP under 2%".

| Config | Mean fold IoU | DSAD FP | Note |
|---|---|---|---|
| Base, threshold 0.3 | 0.297 | 14.6% | fails the FP rule |
| Base, threshold 0.5 | 0.233 | 5.0% | fails the FP rule |
| **Base, threshold 0.7** | **0.190** | **0.18%** | selected |
| More negatives, strong augmentation, hard-negative mining | 0.025 to 0.045 | — | stopped predicting blood |
| Moderate negatives, strong augmentation, dropout, frozen early encoder, threshold 0.7 | 0.179 | 0.51% | below base |
| Learned AND colour model (both ensembles, all thresholds) | at most 0.056 | at most 2.2% | the colour model misses the training operations' blood |

**Held-out real frames**, final model trained on both blood operations:

| | Precision | Recall | IoU |
|---|---|---|---|
| **Colour model (shipped)** | **63.6%** | 7.7% | — |
| Learned, threshold 0.7 (selected) | 5.9% | 22.1% | 4.9% |
| Learned, threshold 0.3 | 1.8% | 39.8% | 1.7% |

The held-out frames were scored twice: once at the threshold first chosen on validation
(0.3), and once at the threshold the FP rule later selected (0.7). Neither run changed
the model.

**Why the learned model loses here.** With blood labelled in two operations from one centre, the network learned
what those two operations look like rather than what blood looks like. It called 16% of
organ pixels blood on unseen DSAD patients at threshold 0.3, and flagged 26 to 85% of
frames on robotic and Kaplan clips that contain no visible blood. Pushing negatives
harder removed the false positives and the true positives with them.

**What would fix it** is blood labelled across many operations and centres. No public
dataset we could obtain has that. Hand-labelling a few hundred frames from the openly
licensed clips is the realistic route, and it is the next step if this product is
pursued. The training code and the unshipped model are kept outside the release.

---

## Limitations

- **Blood against red tissue by colour.** 63.6% precision on the held-out clips. The
  rule is tuned to be right when it marks something rather than to mark everything, so
  some blood is left unmarked.
- **Scale.** Missing on black-coated shafts and on shafts merged with pale tissue; no
  clip in the corpus passes the scale gate, so no millilitre figure is shown.
- **Onset on a moving laparoscope.** Does not fire. Stabilisation and registration are
  the next step and are not attempted here.
- **Phase and checkpoint.** No real-video validation; the width cue is affected by
  distance.
- **Corpus size.** Everything here rests on 64 labelled frames from a single labeller across
  sixteen clips.
