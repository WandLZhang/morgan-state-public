# Self-hosting open LLMs on Vertex AI endpoints (RTX PRO 6000 / G4)

Deploy **Gemma 4 26B-A4B**, **Llama 3.3 70B**, and **Llama 4 Maverick** as private,
OpenAI-compatible inference endpoints on Google Cloud — using Vertex AI Model Garden's
verified vLLM containers on NVIDIA **RTX PRO 6000 (G4)** GPUs.

---

## What you get

| Model | GPUs | Machine type | Notes |
|---|---|---|---|
| Gemma 4 26B-A4B | 1× RTX PRO 6000 | `g4-standard-48` | MoE (about 4B active), multimodal, 256K ctx |
| Llama 3.3 70B Instruct | 2× RTX PRO 6000 | `g4-standard-96` | Dense, 128K ctx |
| Llama 4 Maverick (FP8) | 8× RTX PRO 6000 | `g4-standard-384` | MoE (about 17B active / 400B total), 1M ctx |

RTX PRO 6000 (96 GB) is on-demand-available, and Model Garden has verified vLLM configs for all three — weights are served from Google-hosted GCS, so there's no Hugging Face token or license gating to wrangle (just `accept_eula=True`).

---

## Estimated monthly cost (all three models, 11 GPUs, us-central1)

List-price estimate. Business-hours = 176 h/mo (9am–5pm Mon–Fri, undeployed otherwise); 24×7 = 730 h/mo.

### RTX PRO 6000 (G4) — on-demand · what this repo deploys

| Model | Machine | Vertex AI SKUs × quantity | $/hr | $/mo business-hrs | $/mo 24×7 |
|---|---|---|---|---|---|
| Gemma 4 26B-A4B | `g4-standard-48` | RTX PRO 6000 GPU ×1 · G4 vCPU ×48 · G4 RAM ×180 GiB | $5.69 | $1,001 | $4,151 |
| Llama 3.3 70B | `g4-standard-96` | RTX PRO 6000 GPU ×2 · G4 vCPU ×96 · G4 RAM ×360 GiB | $11.37 | $2,001 | $8,301 |
| Llama 4 Maverick (FP8) | `g4-standard-384` | RTX PRO 6000 GPU ×8 · G4 vCPU ×384 · G4 RAM ×1,440 GiB | $45.49 | $8,006 | $33,205 |

### H100 (A3) — Vertex pooled accelerators · comparison

| Model | Machine | Vertex AI SKUs × quantity | $/hr | $/mo business-hrs | $/mo 24×7 |
|---|---|---|---|---|---|
| Gemma 4 26B-A4B | `a3-highgpu-1g` | H100 80GB GPU ×1 · A3 vCPU ×26 · A3 RAM ×234 GiB | $14.27 | $2,512 | $10,418 |
| Llama 3.3 70B | `a3-highgpu-2g` | H100 80GB GPU ×2 · A3 vCPU ×52 · A3 RAM ×468 GiB | $28.54 | $5,023 | $20,836 |
| Llama 4 Maverick (FP8) | `a3-highgpu-8g` | H100 80GB GPU ×8 · A3 vCPU ×208 · A3 RAM ×1,872 GiB | $114.17 | $20,094 | $83,343 |

---

## Measured performance (us-central1, 1 replica each)

Workload: **2 queries/sec, 1,000 input tokens, 1,500 output tokens.**

| Model | Warm single request | Sustained 2 QPS load test |
|---|---|---|
| Gemma 4 26B-A4B | about 77 tok/s · first token <1s | ✅ **2.0 QPS, 0 failures**, about 3,000 output tok/s aggregate, e2e p50 about 50s for a full 1,500-token answer |
| Llama 4 Maverick (FP8) | about 62 tok/s · about 1.0s | ✅ **2.0 QPS, 0 failures**, about 2,100 output tok/s aggregate, e2e p50 about 26s |
| Llama 3.3 70B | about 19 tok/s · about 5.0s | ⚠️ **saturates 1 replica** — completes 2.0 QPS but e2e p50 about 188s (p95 about 320s), about 2,400 output tok/s aggregate → run **2 replicas** |

Gemma 4 and Maverick are MoE (only a fraction of weights active per token) → fast. Llama 3.3 70B is **dense** → slowest per token and the only one that needs >1 replica at this load. In a streaming chat UI the user sees the first token in well under a second; the "e2e" column is time to the *complete* 1,500-token answer.

---

## Sizing & scaling

The scripts default to **1 replica, fixed** (`--min-replica 1 --max-replica 1`).

| Model | Change needed for 2 QPS? | Command |
|---|---|---|
| **Gemma 4 26B-A4B** | **No** — 1 replica handles it with headroom | `python deploy.py --model gemma4` |
| Llama 4 Maverick | **No** — 1 replica (8 GPUs) handles it | `python deploy.py --model maverick` |
| Llama 3.3 70B | **Yes** — needs 2 replicas (dense model saturates 1) | `python deploy.py --model llama33 --max-replica 2` |

**To handle growth or bursts beyond 2 QPS**, give any model autoscaling headroom by setting `--max-replica` above 1 — Vertex then adds replicas based on GPU / KV-cache utilization and removes them as load falls. Capacity scales linearly (each replica = the model's GPU footprint), bounded by your RTX PRO 6000 quota. Start conservative and raise `--max-replica` as real traffic grows.

```bash
# autoscaling example: 1-3 replicas based on load
python deploy.py --model gemma4 --min-replica 1 --max-replica 3
```

---

## Quickstart

**Prerequisites:** a Python venv with `google-cloud-aiplatform>=1.60` and `requests`; `gcloud auth application-default login`; RTX PRO 6000 serving quota in your region (`check.py` reports it).

```bash
source /path/to/.venv/bin/activate
export GCP_PROJECT_ID=your-project

python check.py                                   # 1. preflight: deployability + quota
python deploy.py --model gemma4                   # 2. deploy (start here; about 15-30 min)
python bench.py  --model gemma4 --smoke           # 3. one streamed answer + tok/s
python bench.py  --model gemma4 --qps 2 --duration 90 --in-tokens 1000 --out-tokens 1500   # 4. load test
python deploy.py --model gemma4 --teardown        # 5. stop the meter when done
```

Repeat `deploy.py`/`bench.py` with `--model llama33` and `--model maverick` as needed (use `--max-replica 2` for Llama 70B).

---

## Files

| File | Purpose |
|---|---|
| `check.py` | Lists Model Garden deploy options for the 3 models + checks RTX PRO 6000 serving quota. |
| `deploy.py` | Deploys a model to a dedicated Vertex endpoint (region fallback, true SSE streaming), or `--teardown`. |
| `bench.py` | `--smoke` (one streamed request) or load test (`--qps` / `--duration` / `--in-tokens` / `--out-tokens`). |
| `endpoint-<model>.json` | Written by `deploy.py`; holds the live endpoint id/region (git-ignored — environment-specific). |

---

## Notes

- **Why RTX PRO 6000 (G4)?** On-demand-available and Model-Garden-verified for all three models; 96 GB/GPU comfortably holds Gemma 4 (1 GPU), Llama 70B (2), and Maverick FP8 (8).
- **Request format.** Dedicated endpoints take the Vertex `@requestFormat: chatCompletions` wrapper (applies the chat template, returns an OpenAI-style `chat.completion` with token usage) — see `bench.py`.
- **Alternatives.** Fully-managed per-token serving (Model Garden MaaS) avoids running infrastructure; **Cloud Run GPU + RTX PRO 6000** adds true scale-to-zero and suits Gemma 4's mostly-idle pattern (Llama 70B / Maverick are too large for Cloud Run's startup limits).
