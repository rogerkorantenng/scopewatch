# Scopewatch: Devpost submission

Paste each section below into the matching Devpost field.

- Live: <https://s3vrzphtvv.eu-central-1.awsapprunner.com>
- Repository: <https://github.com/rogerkorantenng/scopewatch>
- OpenCV 5.0.0 (`opencv-python-headless==5.0.0.93`), pinned, on AWS App Runner

## Inspiration

In the United States, postpartum haemorrhage causes about 11% of maternal deaths and is
the leading cause of death on the day a baby is born. California reviews every one of
those deaths: across 2.4 million births, an expert panel judged **63% of haemorrhage
deaths highly preventable**, and found **delayed recognition in 72% of them**.
(California Pregnancy-Associated Mortality Review, *Obstet Gynecol* 2025.)

The American College of Obstetricians and Gynecologists names the cause directly:
imprecise estimation of actual blood loss is "a leading cause of delayed response to
hemorrhage" (Committee Opinion 794).

Measured against haematocrit, visual estimation underestimated the loss in 90% of cases;
a fifth of those patients had lost over a litre, and by eye none of them had haemorrhaged
at all. The same shape appears in surgery: across 548 recorded gallbladder operations the
safety step that prevents bile duct injury was recorded in 61% of cases.

Both have the same shape: the information is already in front of a camera already in the
room, and a person under time pressure is asked to judge it by eye.

## What it does

Scopewatch reads the laparoscopic camera feed and measures the operating field.

**On clips held out from tuning, 63.6% of the pixels it calls blood are blood. Across
all fifteen laparoscopic clips, 78.2%.** Those figures are scored against masks drawn by
hand on 64 frames by a labeller who never saw the product's output, split by clip so a
shared scope, light source and patient cannot leak between halves.

- **Blood-covered field** — the share of the visible field that is blood, per frame, and
  how fast it is changing.
- **Volume, refused unless the scale holds** — millilitres need a scale, taken from
  instrument shafts of known diameter. Where the scale is not steady, the row reads
  `CANNOT_MEASURE` and names the reason rather than printing a number it cannot support.
- **Bleeding onset** — a trailing-window slope confirmed by CUSUM, gated on camera
  motion. When it does not fire, the screen names the gate that held it.
- **Refusals** — focus, fog, occlusion, exposure, and `OUT_OF_DOMAIN` for open surgery.

Refusing is the feature. A tool that reports a number through smoke is worse than one
that stops.

## How we built it

A pixel is blood when it clears three tests at once: Lab chroma above an absolute floor,
chroma-per-lightness above a multiple of the scene's own median, and a hue inside a band
around that median. Blood is deeply coloured for how light it is; shadow is dark and
grey; pink tissue is coloured but light. Darkness is never used as evidence.

The three constants are chosen by maximising F-0.5 under leave-one-clip-out — precision
weighted over recall, because a surgical overlay should be right when it marks something.

Four findings shaped the implementation:

- **Otsu fails on a minority class.** It assumes two comparable populations, so on a
  frame where blood covers a few per cent it splits the *tissue* instead and returns half
  the abdomen. Every candidate thresholds against the tissue mode: find the dominant
  histogram peak, measure its spread on the side the target cannot contaminate, take four
  sigma above it.
- **Lab compresses dark colours.** A dark saturated red sits at a\* 165 against tissue at
  149 ± 5 — four sigma is 167, so a pool falls on the wrong side. Normalised redness is a
  ratio and has no such compression.
- **The scope's own light looks like blood.** The source sits at the tip, so the periphery
  is half as bright as the centre. Illumination is divided out with the candidate region
  excluded — leave it in and a large pool flattens its own surroundings.
- **A surface vessel is redder and darker than tissue and is not blood loss.** What
  separates them is shape, measured on the medial axis with `distanceTransform`.

We also trained a learned segmenter to replace the colour rule: MobileNetV3 with an FPN
decoder, trained in PyTorch, exported to ONNX, run through OpenCV 5's own `cv2.dnn`. On
the same held-out frames it reached 5.9%. **On a corpus this size the classical method
wins by an order of magnitude**, and it is what ships.

## What makes it agentic

The visual result changes what the pipeline does next, not just what it prints:

| Perception | Decision | Action |
|---|---|---|
| A rate of change in the coarse pass | onset plausible but poorly localised | re-read that ten-second window at full frame rate |
| Three consecutive frames refused for fog | the series cannot be trusted | suppress the onset detector, raise a clean-lens request |
| Phase reaches critical approach with no safety view | the irreversible step may be near | hold a checkpoint until a named person answers |

A clip with no bleed never triggers a second read, and there is a test for that.

## Accomplishments

- Held-out precision of 63.6%, and 78.2% across all laparoscopic clips.
- A classical colour rule that beats a trained CNN on the same frames, 63.6% to 5.9%.
- Refusals that name their reason — the product declines rather than guesses.
- Apache-2.0 and BSD only. Nothing imports `ultralytics`; no AGPL anywhere, which
  matters because AGPL section 13 extends copyleft to a hosted demo.

## What's next

- **More labelled clips.** Each one adds roughly 3.5 points of held-out precision, so
  the next gain is data rather than modelling.
- **Motion.** Onset needs image registration before a rate means anything on a handheld
  scope.
- **Labelled clinical video.** Endoscapes and CholecT50 sit behind registration forms.

## Built with

OpenCV 5, Python, FastAPI, ONNX, YOLOX-tiny (Apache-2.0), AWS App Runner, ECR, S3.

## Try it out

Press **Run the bundled sample** — a 93-second laparoscopic repair of a bleeding ulcer
ships inside the image, so no file of your own is needed. The blood-covered field peaks
around 30%, and the volume row reads `CANNOT_MEASURE` with its reason.

Then upload `sample-unmeasurable.mp4` from the repository to see the screen where the
tool declines to answer.

## Limitations

Scopewatch is tuned to be right when it marks something, so some blood is left unmarked.
No clip in this corpus passes the scale gate, so no millilitre figure is shown. The
bleeding onset does not fire on a moving laparoscope. Everything rests on 64 labelled
frames across sixteen clips.

It is a retrospective measurement instrument, not a medical device, and it takes no
clinical action.
## Footage credits

Shown in the film (all transcoded; interior views only):

- **"Diagnosis and treatment of perforated or bleeding peptic ulcers: 2013 WSES position
  paper", supplementary video (laparoscopic repair of a bleeding ulcer).** Di Saverio S,
  Bassi M, Smerieri N, et al., *World Journal of Emergency Surgery* 2014,
  doi:10.1186/1749-7922-9-45. CC BY 4.0.
  <https://commons.wikimedia.org/wiki/File:Diagnosis-and-treatment-of-perforated-or-bleeding-peptic-ulcers-2013-WSES-position-paper-1749-7922-9-45-S1.ogv>
- **"Learning Curves for Laparoscopic Repair of Inguinal Hernia and Communicating
  Hydrocele in Children", video 1.** Barroso C, Etlinger P, Alves A, et al., *Frontiers
  in Pediatrics* 2017, doi:10.3389/fped.2017.00207. CC BY 4.0.
  <https://commons.wikimedia.org/wiki/File:Learning-Curves-for-Laparoscopic-Repair-of-Inguinal-Hernia-and-Communicating-Hydrocele-in-Children-video_1.ogv>
- **"TEP Operation of Groin Hernia Video 3".** Anpol42, Wikimedia Commons, own work,
  2012. CC BY-SA 3.0.
  <https://commons.wikimedia.org/wiki/File:TEP_Operation_of_Groin_Hernia_Video_3.ogv>
- **"Torsion of gall bladder, a rare entity: a case report and review article",
  supplementary video (open cholecystectomy).** Gupta V, Singh V, Sewkani A, et al.,
  *Cases Journal* 2009, doi:10.1186/1757-1626-2-193. CC BY 2.0.
  <https://commons.wikimedia.org/wiki/File:Torsion-of-gall-bladder-a-rare-entity-a-case-report-and-review-article-1757-1626-2-193-S1.ogv>

Used for evaluation only; no imagery shown:

- Anpol42 TEP hernia videos 1, 2 and 4, the recurrent-hernia view and the indirect-hernia
  view, Wikimedia Commons, CC BY-SA 3.0.
- Kaplan M, total laparoscopic pancreaticoduodenectomy, videos 1, 3, 5 and 6, *World
  Journal of Surgical Oncology* 2012, doi:10.1186/1477-7819-10-142, CC BY 2.0, via
  Wikimedia Commons.
- Boer J, Boerma D, de Vries Reilingh T, laparoscopic cholecystectomy, *Journal of
  Medical Case Reports* 2011, doi:10.1186/1752-1947-5-588, CC BY 2.0, via Wikimedia
  Commons.
- Kavalakat A, Varghese C, laparoscopic omentectomy, *Cases Journal* 2008,
  doi:10.1186/1757-1626-1-164, CC BY 2.0, via Wikimedia Commons.
- ADM_LSIR surgical aerosol frames D-V09-0000 to D-V09-0101, Guo N et al., Zenodo 2026,
  doi:10.5281/zenodo.20470138, CC BY 4.0.

Source page, author and licence for every clip are listed in `src/scopewatch/realdata.py`
(`realdata.CLIPS`); per-clip results are in Part A of `docs/evaluation.md`.
