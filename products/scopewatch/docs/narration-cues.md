# Narration cues: Scopewatch

Audio `Scopewatch.mp3`, **286.56 s** (4:46), transcribed with whisper small.en on the
GPU; word timings in `/tmp/sw-vid/tx.json`. Every time below is a word-level start
from that transcript, not an estimate.

Whisper renders numbers as digits, "App Runner" as "AppRunner", and splits
"The same shape / in surgery" across a segment boundary.

## Act 1 — slides (0:00 to 1:56)

| On screen | Cue | In | Out |
|---|---|---|---|
| `s01` title | "Hi, I'm Roger" | 0.00 | 14.92 |
| `s02` 11% | "In the United States, postpartum" | 14.92 | 25.06 |
| `s03` 63% | "California reviews every one" | 25.06 | 40.20 |
| `s04` 72% | "delayed recognition. Somebody did not" | 40.20 | 44.90 |
| `s05` ACOG quote | "The American College of Obstetricians" | 44.90 | 59.54 |
| `s06` 90% | "Measured against haematocrit" | 59.54 | 73.00 |
| `s07` surgery | "The same shape" | 73.00 | 95.74 |
| `s08` our 64% | "Scopewatch measures it instead" | 95.74 | 116.12 |

## Act 2 — the live app (1:56 to 4:19)

Recorded against the live service at `s3vrzphtvv.eu-central-1.awsapprunner.com`,
steps in `tools/video/steps/scopewatch-v2.json`. Four real clips, uploaded in order.

| Beat | Cue | At | Highlight |
|---|---|---|---|
| WSES clip plays | "This is a laparoscopic repair" | 116.12 | `#video` |
| the rule | "A pixel is blood when it clears" | ~130 | `#kpis` |
| field trace | "Here is the field trace" | 152.38 | `#field-trace` |
| volume refused | "Now the volume row" | 161.40 | `#kpis > .kpi:nth-child(2)` |
| why no scale | "Scale comes from an instrument shaft" | ~163 | `#instruments` |
| evidence panel | "This is the evidence behind the numbers" | 183.20 | `#evidence` |
| open surgery refused | "Here is open surgery" | 199.58 | `#cannot` |
| rim and sleeve | "rim of the scope's circle reads zero" | 210.54 | `#kpis` |
| OpenCV 5, App Runner | "The pipeline is" | 223.74 | — |
| learned vs colour | "We also trained a learned segmenter" | 235.86 | — |

## Act 3 — closing slides (4:19 to 4:46)

| On screen | Cue | In | Out |
|---|---|---|---|
| `s09` limitations | "Scopewatch is tuned to be right" | 259.44 | 273.06 |
| `s10` +3.5 points | "What comes next" | 273.06 | 281.84 |
| `s11` closing | "It is a measurement instrument" | 281.84 | 286.56 |

## Footage credits (sources card, not spoken)

- Laparoscopic repair of a bleeding ulcer. Di Saverio S et al., World J Emerg Surg
  2014, doi:10.1186/1749-7922-9-45. CC BY 4.0. Transcoded.
- Laparoscopic inguinal hernia repair. Barroso C et al., Front Pediatr 2017,
  doi:10.3389/fped.2017.00207. CC BY 4.0. Transcoded.
- Open cholecystectomy. Gupta V et al., Cases J 2009, doi:10.1186/1757-1626-2-193.
  CC BY 2.0. Transcoded.
- Slide backgrounds: frames from the Kaplan laparoscopic clips (open licence), plus
  public domain and CC0 images from Wikimedia Commons. See
  `submissions/scopewatch/slides/IMAGE-CREDITS.txt`.
