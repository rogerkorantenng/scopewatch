# What Scopewatch costs to run

Account `<aws-account-id>`, everything tagged `Project=opencv26` and
`Product=scopewatch`. This is the per-product detail behind the workspace figure in
`../../../docs/costs.md`.

**Region, and why it is not us-east-1.** The plan was us-east-1. App Runner on this
account is restricted to **two services per region**, and at deploy time all three
US regions were at that cap with other projects: us-east-1 held `ugjcs-backend` and
`cairn-v2`, us-east-2 held `opencv26-preempt` and `recourse`, and us-west-2 held
`muster` and `gleaner`. `CreateService` returns
`InvalidRequestException: Account <aws-account-id> is restricted and can support only
two App Runner services per region at the moment`. eu-central-1 had both slots free
and no other agent deploying into it, so Scopewatch runs in **Frankfurt**. The ECR
repository and the image were rebuilt there; App Runner pulls from ECR in its own
region.

**A caveat on the rates below.** Every price quoted in this document is the published
**us-east-1** rate, because that is what was verified. The
service runs in eu-central-1 and I did not separately verify Frankfurt's rates, which
for App Runner and ECR are typically the same or within a few per cent. The totals are
therefore an estimate carrying that much uncertainty, and they are marked as such
rather than presented as a bill.

For a US judge this adds roughly 100 ms of round-trip latency and nothing else. If a
US slot frees up before judging, moving is one `AWS_REGION=us-east-1 ./infra/deploy.sh`
away, because the script takes the region from the environment.

Sizing decision on the record: Scopewatch runs at **2 vCPU / 4 GB, always on**.
That is roughly eight times the 0.25 vCPU / 0.5 GB line the workspace plan
assumed for a product, and it is deliberate — cost is not a constraint for this
entry, and a 960-pixel video pipeline on a quarter vCPU turns a judge's first
click into a timeout. The arithmetic below is what that choice costs.

## What exists right now

| Resource | Identifier | Created by | State |
|---|---|---|---|
| ECR repository, us-east-1 | `<aws-account-id>.dkr.ecr.us-east-1.amazonaws.com/opencv26/scopewatch` | `infra/ecr.sh scopewatch --repo-only` | holds the first build; unused after the region change |
| ECR repository, eu-central-1 | `<aws-account-id>.dkr.ecr.eu-central-1.amazonaws.com/opencv26/scopewatch` | `infra/deploy.sh` with `AWS_REGION=eu-central-1` | the image the service runs |
| S3 prefix | `s3://opencv26-artifacts-<aws-account-id>/scopewatch/` | `aws s3api put-object` | one zero-byte marker |
| S3 bucket | `opencv26-artifacts-<aws-account-id>` | `infra/s3.sh` | pre-existing, shared by all products |
| App Runner service | `opencv26-scopewatch`, eu-central-1 | `infra/deploy.sh` | RUNNING at 2 vCPU / 4 GB, always on |
| **Live URL** | **https://s3vrzphtvv.eu-central-1.awsapprunner.com** | | health check passing, OpenCV 5.0.0 on x86_64 |

An empty ECR repository and a zero-byte S3 key cost nothing on their own. The two
image copies do: see the ECR line below.

## App Runner, 2 vCPU / 4 GB

Two separate meters, and the difference between them is the whole story.

**Provisioned memory — billed every hour the instance exists, busy or idle.**

```
$0.007 per GB-hour  x  4 GB                    = $0.028 per hour
$0.028 per hour     x  730 hours in a month    = $20.44 per month
```

**Active vCPU — billed only while a request is actually being processed.**

```
$0.064 per vCPU-hour  x  2 vCPU  = $0.128 per hour of request time
```

An idle hour costs $0.028. An hour spent flat out analysing video costs
$0.028 + $0.128 = **$0.156**. The vCPU meter is the one that only runs when a
request is in flight; the memory meter never stops while the service is up.
"Always on" therefore has a floor of $20.44/month and no ceiling until the
service is busy.

What the vCPU side adds at a few levels of use:

| Active request time per month | vCPU charge | + memory | Monthly total |
|---|---:|---:|---:|
| 0 hr (nobody visits) | $0.00 | $20.44 | **$20.44** |
| 10 hr | $1.28 | $20.44 | **$21.72** |
| 30 hr (a realistic judging month) | $3.84 | $20.44 | **$24.28** |
| 730 hr (saturated, every hour of the month) | $93.44 | $20.44 | **$113.88** |

Source for both rates: the AWS App Runner pricing page, $0.007/GB-hr provisioned
memory and $0.064/vCPU-hr active compute, us-east-1. The same two figures give
the ~$2.52/month idle cost of a 0.25 vCPU / 0.5 GB service. 730 hours is AWS's own
month (365 x 24 / 12).

App Runner has no free tier. Data transfer out of the public endpoint is billed
at standard rates and is not modelled here: the sample clip is 7.6 MB and a
judging session moves a few hundred megabytes at most, so it rounds to cents.
That figure is **unverified** — I did not look up App Runner's egress rate.

## ECR storage

$0.10 per GB-month for private repository storage, us-east-1, from the Amazon ECR
pricing page. This is the published list price. ECR bills the compressed size of the layers it stores.

The image has not been built yet, so its size is an **estimate**, not a
measurement:

| Layer | Uncompressed | Compressed, estimated |
|---|---:|---:|
| `python:3.13-slim-bookworm` + libglib + curl | ~140 MB | ~50 MB |
| venv: opencv-python-headless 5.0.0.93 (72 MB) + numpy (33 MB) + FastAPI/uvicorn/pydantic | ~150 MB | ~70 MB |
| `yolox_tiny.onnx` | 19.3 MB | ~19 MB (ONNX weights barely compress) |
| `sample-case.mp4` | 7.6 MB | 7.6 MB (already H.264) |
| source tree | ~2 MB | <1 MB |
| **per image** | **~320 MB** | **~150 MB** |

The base and venv layers are shared across tags, so ten tags is not ten times
that. With `infra/ecr.sh`'s lifecycle policy — untagged expire after a day, keep
the last 10 images — plus the `buildcache` blob that `--cache-to mode=max`
pushes, budget **1 to 2 GB stored**:

```
1.5 GB  x  $0.10 per GB-month  =  $0.15 per month
```

Replace the estimate with a fact after the first push:

```bash
aws ecr describe-images --repository-name opencv26/scopewatch \
  --query 'sum(imageDetails[].imageSizeInBytes)' --output text
```

Basic scan-on-push, which `infra/ecr.sh` enables, is free.

## S3

$0.023 per GB-month, S3 Standard, first 50 TB, us-east-1.

The `scopewatch/` prefix currently holds one zero-byte object, so the charge is
**$0.00**. If evidence frames and benchmark output start landing there, 1 GB is
$0.023/month — and the bucket's lifecycle rule deletes objects after 30 days and
non-current versions after 7, so the stored total cannot quietly climb.

One wrinkle worth knowing: that 30-day expiry applies to the zero-byte prefix
marker too, so it will disappear around 17 October 2026. Nothing breaks. S3
prefixes are not directories; the first real upload recreates it.

## Total

| Item | $/month |
|---|---:|
| App Runner, 2 vCPU / 4 GB, always on, ~30 hr active | 24.28 |
| ECR storage, eu-central-1, the image the service runs (~1.1 GB) | 0.11 |
| ECR storage, us-east-1, the first build, now unused | 0.11 |
| S3 under `scopewatch/` | 0.00 |
| **Total** | **~$24.50** |

The us-east-1 repository is a leftover of the region change and is the one line here
worth deleting: `aws ecr delete-repository --repository-name opencv26/scopewatch
--region us-east-1 --force` takes eleven cents off and removes nothing the live service
uses. It is left in place for now because it holds the first image that was built and
pushed, and eleven cents is cheaper than needing it back.

Against the workspace's $80/month budget, Scopewatch alone takes about 30% of
it, nearly all of it the always-on memory reservation. Compared with running the
same service at the workspace default of 0.25 vCPU / 0.5 GB (~$2.52/month idle),
this sizing costs about $22/month more. That was the trade accepted for a demo
that responds on the first click.

## After judging

**Tear down** — `infra/apprunner.sh scopewatch --delete`. The App Runner service
is the entire bill. Deleting it takes the monthly cost from ~$24 to ~$0.15, and
`infra/deploy.sh` rebuilds it from the same image in about five minutes when it
is next needed.

**Keep** — the ECR repository and the S3 prefix. Together they are about fifteen
cents a month, they hold the artefact that proves what was submitted, and the
lifecycle policies already stop either of them growing without limit. Deleting
the repository to save $0.15 would mean the submitted image no longer exists.
