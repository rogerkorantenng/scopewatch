# Scopewatch architecture

Three diagrams: the vision pipeline, the agent loop the Agentic Vision award asks
for, and the AWS components.

---

## 1. The vision pipeline

Everything in the shaded band is OpenCV 5. The order is deliberate: the quality gates
run **before** the segmenter, so there is no code path in which an unmeasurable frame
produces a number that something downstream could pick up.

```mermaid
flowchart TD
    A["Video or image upload<br/>(or the bundled sample)"] --> B["cv2.VideoCapture<br/>decimated at stride N"]

    subgraph OCV["OpenCV 5.0.0.93"]
        direction TB
        B --> C["Field mask<br/>cvtColor, morphologyEx,<br/>connectedComponentsWithStats"]
        C --> D{"Quality gates"}
        D -->|"Laplacian variance<br/>below 25"| R1["refuse OUT_OF_FOCUS"]
        D -->|"dark channel above 132<br/>and contrast below 22"| R2["refuse LENS_FOGGED"]
        D -->|"achromatic flat region<br/>over 55% of the field"| R3["refuse OCCLUDED"]
        D -->|"clipped pixels<br/>over 34%"| R4["refuse EXPOSURE_CLIPPED"]
        D -->|"measurable"| E["Instrument shafts<br/>HSV threshold, morphologyEx,<br/>connectedComponentsWithStats,<br/>minAreaRect, distanceTransform"]

        E --> F{"A shaft crossing<br/>the field edge?"}
        F -->|no| R5["refuse NO_SCALE_REFERENCE<br/>(area fraction still reported)"]
        F -->|yes| G["Scale<br/>5 mm / medial-axis width px<br/>= mm per pixel, with sigma"]

        E --> H["YOLOX-tiny via cv2.dnn<br/>ONNX, Apache-2.0<br/>every 10th kept frame"]

        D -->|"measurable"| I["Blood segmentation<br/>redness ratio (R-G)/(R+G)<br/>AND flattened L* darkness<br/>GaussianBlur, calcHist,<br/>morphologyEx, distanceTransform"]
        I --> J["Area in pixels<br/>pools kept by area and width"]
        G --> K["Area in mm squared<br/>then volume interval<br/>over a 1 to 3 mm film depth"]
        J --> K

        B --> L["Camera motion<br/>cv2.phaseCorrelate<br/>on a 256 px Hanning window"]
    end

    K --> M["Series: median filter,<br/>exponential moving average"]
    L --> M
    M --> N["Rate: least squares slope<br/>over a 4 s trailing window"]
    M --> O["CUSUM, thresholds scaled<br/>from the series' own noise"]
    N --> P{"Onset?"}
    O --> P
    L --> P
    P -->|"slope above threshold,<br/>CUSUM agrees,<br/>field not moving"| Q["Bleeding onset<br/>timestamp +/- the window"]

    E --> S["Phase features:<br/>instrument count, shaft widths,<br/>tip motion, blood fraction"]
    S --> T["Phase state machine<br/>with hysteresis"]

    Q --> U["Agent loop"]
    T --> U
    R2 --> U
    U --> V["RunRecord:<br/>numbers, intervals, refusals,<br/>timings, evidence frames,<br/>every agent transition"]

    style OCV fill:#141F1B,stroke:#FF8A3D,color:#E9F1EC
```

---

## 2. The agent loop

The competition rules state the bar: *"image or video results must influence a
subsequent plan, tool call, action, or request for human approval... the visual
evidence must change what the system does next."*

Three closures. Each one changes what the pipeline does, not what it prints.

```mermaid
stateDiagram-v2
    direction LR

    [*] --> observing

    state "observing" as observing
    state "candidate" as candidate
    state "held" as held
    state "confirmed" as confirmed
    state "dismissed" as dismissed

    observing --> candidate : phase entered critical_approach<br/>and no safety view recorded
    candidate --> observing : phase left critical_approach<br/>(action: resume)
    candidate --> held : held for 1.5 s<br/>(action: hold_checkpoint)
    held --> confirmed : a named person confirms<br/>the critical view of safety
    held --> dismissed : a named person dismisses,<br/>with a reason from a fixed list
    confirmed --> [*]
    dismissed --> [*]

    note right of held
      Nothing resolves this but a person.
      No timeout. No auto-clear.
      Feed it a hundred more frames
      and it stays held.
    end note
```

The two loops that run alongside the state machine:

```mermaid
flowchart LR
    subgraph L1["Loop 1: the second look"]
        A1["Coarse pass at stride 5"] --> B1["Rate of change crosses<br/>the threshold"]
        B1 --> C1["action: rescan_window<br/>start -5 s, end +5 s, stride 1"]
        C1 --> D1["Re-open the file<br/>and read that window densely"]
        D1 --> E1["The dense onset replaces<br/>the coarse one"]
    end

    subgraph L2["Loop 2: the lens"]
        A2["Three consecutive frames<br/>refused for fogging"] --> B2["The series cannot be trusted:<br/>a white-out looks like<br/>a field filling with blood"]
        B2 --> C2["action: request_clean_lens<br/>onset detection suppressed"]
    end
```

A clip with no bleed in it never triggers loop 1. That is what makes it a loop rather
than a fixed sequence, and it is asserted in
`tests/test_pipeline.py::test_a_quiet_case_never_triggers_a_second_read`.

**Autonomy, stated plainly.** Scopewatch takes no clinical action. It measures, it
asks, and it records what a person decided. Every checkpoint is resolved by a named
human; none expires, times out or resolves itself. The service refuses an anonymous
confirmation and refuses a dismissal with no reason, and both refusals are tested.

---

## 3. AWS

```mermaid
flowchart TD
    U["Judge's browser"] -->|HTTPS| AR

    subgraph AWS["AWS us-east-1, account <aws-account-id>, everything tagged Project=opencv26"]
        AR["App Runner service<br/>scopewatch<br/>2 vCPU / 4 GB, always on<br/>x86_64 (App Runner has no ARM option)"]
        ECR["ECR repository<br/>opencv26/scopewatch<br/>image carries opencv-python-headless 5.0.0.93,<br/>the YOLOX-tiny ONNX and the sample clip"]
        S3["S3 bucket<br/>opencv26-artifacts-<aws-account-id><br/>prefix scopewatch/<br/>sample media and result artefacts"]
        CW["CloudWatch Logs<br/>application and service logs"]

        ECR -->|"image pull on deploy"| AR
        AR --> CW
        AR -.->|"artefact write"| S3
    end

    DEV["infra/deploy.sh<br/>docker build from the repo root"] -->|"push"| ECR
    DEV -->|"create or update, then poll<br/>until RUNNING"| AR
```

**Why App Runner and not Lambda or EC2.** The endpoint has to work for a judge from a
cold start with one click and no local file, over an unattended two-week judging
window. App Runner gives an always-on HTTPS endpoint with a managed certificate and no
load balancer, which matters because an ALB costs about $16 a month at zero traffic
and five entries would pay it five times. Lambda would have been cheaper still, but a
one-to-two gigabyte OpenCV container's cold start is unmeasured and a judge who waits
thirty seconds for a first response has already formed a view. EC2 would have needed a
certificate and a reverse proxy we would then have to keep alive.

**Why x86_64 and not Graviton.** App Runner exposes no ARM option in its pricing, its
FAQ or its API parameters. The aarch64 OpenCV 5 wheel does ship Arm's KleidiCV HAL, so
there is a real Graviton story available, but it needs EC2 or ECS and this product's
judging requirement is an endpoint that is simply up. The trade is recorded here
rather than hidden.

**Costs**: [costs.md](costs.md).

---

## 4. Where the OpenCV 5 work actually is

Measured on this machine at 960 x 540 with 22 threads, `opencv-python==5.0.0.93`.
The numbers are regenerated by `python -m scopewatch.evaluate` and published in
`docs/evaluation.json` under `timing`.

| Stage | What it calls | ms/frame |
|---|---|---|
| Field mask | `cvtColor`, `morphologyEx` x2, `connectedComponentsWithStats` | ~1.8 |
| Quality gates | `Laplacian`, `erode`, `Sobel`, `magnitude`, `morphologyEx`, `connectedComponentsWithStats` | ~13.3 |
| Blood segmentation | `cvtColor`, `calcHist`, `GaussianBlur`, `morphologyEx` x2, `distanceTransform` | ~4.3 |
| Instrument shafts | `cvtColor`, `morphologyEx` x2, `connectedComponentsWithStats`, `findContours`, `minAreaRect`, `distanceTransform` | ~11.7 |
| Camera motion | `resize`, `createHanningWindow`, `phaseCorrelate` | ~0.6 |
| YOLOX-tiny | `cv2.dnn.readNetFromONNX`, `blobFromImage`, `forward` | ~13.6, every 10th frame |

Two OpenCV 5 specifics the code depends on:

- **`cv2.dnn` is ONNX-only in 5.x.** `readNetFromCaffe` and `readNetFromDarknet` were
  removed, which is one more reason YOLOX's official ONNX export is the right choice
  and Darknet YOLOv4 weights are not.
- **`cv2.FontFace`** is used for the evidence-frame annotations. The legacy
  `FONT_HERSHEY_*` path renders through a TrueType engine in 5.x and looks different
  from 4.x, so the code asks for `FontFace("sans")` explicitly rather than inheriting
  whatever the legacy constant now means.
