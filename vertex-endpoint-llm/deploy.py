#!/usr/bin/env python3
"""
Deploy (or tear down) Morgan State open-weight models as private,
OpenAI-compatible inference endpoints on Vertex AI, self-hosted on NVIDIA
RTX PRO 6000 (G4) GPUs via Model Garden's verified vLLM serving containers.

Why RTX PRO 6000 (G4): on-demand-available (H100/H200 are pool-only / capacity
constrained), 96 GB/GPU, about 2.5x cheaper than H100 on Vertex, and Model Garden has
verified configs for all three models. Weights are served from Google-hosted GCS,
so there is NO Hugging Face token or Llama gating to manage.

Usage:
    source /path/to/.venv/bin/activate
    GCP_PROJECT_ID=<your-project> python deploy.py --model gemma4
    GCP_PROJECT_ID=<your-project> python deploy.py --model llama33
    GCP_PROJECT_ID=<your-project> python deploy.py --model maverick
    # tear down (stop the meter):
    GCP_PROJECT_ID=<your-project> python deploy.py --model gemma4 --teardown

Writes endpoint-<model>.json next to this script (consumed by bench.py / teardown).
"""
import argparse
import json
import os
import sys
import time

# --- Force project resolution -------------------------------------------------
# The ADC default quota project and the GOOGLE_CLOUD_PROJECT env var can point at
# a stale/deleted or unrelated project, which makes the Vertex / Model Garden SDK
# fail. Pin the project + quota project explicitly so this script is self-contained.
# Override with: GCP_PROJECT_ID=<your-project> python deploy.py ...
PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "wz-msu-test")
os.environ.pop("GOOGLE_CLOUD_PROJECT", None)
os.environ.pop("GCLOUD_PROJECT", None)
os.environ["GOOGLE_CLOUD_QUOTA_PROJECT"] = PROJECT_ID

import google.auth  # noqa: E402
import vertexai  # noqa: E402
from google.cloud import aiplatform  # noqa: E402
from vertexai import model_garden  # noqa: E402

# Per-model serving config — accelerator picks are Model-Garden-verified
# (confirm with check.py / OpenModel.list_deploy_options()).
MODELS = {
    "gemma4": {
        "model_id": "google/gemma4@gemma-4-26b-a4b-it",
        "display": "msu-gemma4-26b-a4b",
        "machine_type": "g4-standard-48",
        "accelerator_count": 1,
    },
    "llama33": {
        "model_id": "meta/llama3-3@llama-3.3-70b-instruct",
        "display": "msu-llama33-70b",
        "machine_type": "g4-standard-96",
        "accelerator_count": 2,
    },
    "maverick": {
        "model_id": "meta/llama4@llama-4-maverick-17b-128e-instruct-fp8",
        "display": "msu-llama4-maverick-fp8",
        "machine_type": "g4-standard-384",
        "accelerator_count": 8,
    },
}
ACCELERATOR_TYPE = "NVIDIA_RTX_PRO_6000"
REGIONS_DEFAULT = ["us-central1", "europe-west4", "asia-southeast1"]
HERE = os.path.dirname(os.path.abspath(__file__))


def ep_file(model_key):
    return os.path.join(HERE, f"endpoint-{model_key}.json")


def deploy(model_key, region_override, min_replica, max_replica, creds):
    cfg = MODELS[model_key]
    regions = [region_override] if region_override else REGIONS_DEFAULT
    print(f"Project:   {PROJECT_ID}")
    print(f"Model:     {cfg['model_id']}")
    print(f"Machine:   {cfg['machine_type']} + {cfg['accelerator_count']}x {ACCELERATOR_TYPE}")
    print(f"Replicas:  min={min_replica} max={max_replica}")
    print(f"Regions:   {', '.join(regions)}\n", flush=True)

    for region in regions:
        print("=" * 60)
        print(f"  Deploying in {region} (15-30 min)...")
        print("=" * 60, flush=True)
        try:
            vertexai.init(project=PROJECT_ID, location=region, credentials=creds)
            t0 = time.time()
            endpoint = model_garden.OpenModel(cfg["model_id"]).deploy(
                accept_eula=True,
                machine_type=cfg["machine_type"],
                accelerator_type=ACCELERATOR_TYPE,
                accelerator_count=cfg["accelerator_count"],
                min_replica_count=min_replica,
                max_replica_count=max_replica,
                use_dedicated_endpoint=True,
                endpoint_display_name=f"{cfg['display']}-endpoint",
                model_display_name=cfg["display"],
                deploy_request_timeout=3600,
            )
            dt = time.time() - t0
            parts = endpoint.resource_name.split("/")
            info = {
                "model_key": model_key,
                "model_id": cfg["model_id"],
                "endpoint_id": parts[-1],
                "resource_name": endpoint.resource_name,
                "project_number": parts[1] if len(parts) > 1 else "",
                "region": region,
                "dedicated_dns": getattr(endpoint.gca_resource, "dedicated_endpoint_dns", "") or "",
                "project_id": PROJECT_ID,
                "machine_type": cfg["machine_type"],
                "accelerator": f"{cfg['accelerator_count']}x {ACCELERATOR_TYPE}",
                "min_replica": min_replica,
                "max_replica": max_replica,
                "deploy_seconds": round(dt),
                "deployed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            with open(ep_file(model_key), "w") as f:
                json.dump(info, f, indent=2)
            print(f"\nDEPLOYED in {dt/60:.1f} min")
            print(json.dumps(info, indent=2))
            print(f"\nSaved: {ep_file(model_key)}")
            return
        except Exception as e:  # noqa: BLE001
            es = str(e)
            print(f"  FAILED in {region}: {es[:400]}", flush=True)
            if any(k in es.lower() for k in ("503", "unavailable", "quota", "capacity",
                                             "resourcelocations", "org policy", "stockout", "exhaust")):
                print("  -> capacity/policy issue, trying next region", flush=True)
                continue
            raise
    sys.exit(f"ERROR: all regions exhausted for {model_key}")


def teardown(model_key, creds):
    f = ep_file(model_key)
    if not os.path.exists(f):
        sys.exit(f"ERROR: {f} not found — nothing to tear down")
    info = json.load(open(f))
    vertexai.init(project=PROJECT_ID, location=info["region"], credentials=creds)
    ep = aiplatform.Endpoint(info["resource_name"])
    print(f"Undeploying all models from {info['endpoint_id']} ({info['region']})...")
    ep.undeploy_all()
    print("Deleting endpoint...")
    ep.delete(force=True)
    os.rename(f, f + ".torndown")
    print(f"Torn down. (renamed {os.path.basename(f)} -> {os.path.basename(f)}.torndown)")


def main():
    ap = argparse.ArgumentParser(description="Deploy/teardown an Morgan State model on Vertex AI (RTX PRO 6000)")
    ap.add_argument("--model", required=True, choices=list(MODELS))
    ap.add_argument("--teardown", action="store_true", help="Undeploy + delete the endpoint")
    ap.add_argument("--region", default="", help="Override region (default: us-central1, europe-west4, asia-southeast1)")
    ap.add_argument("--min-replica", type=int, default=1)
    ap.add_argument("--max-replica", type=int, default=1)
    args = ap.parse_args()

    creds, _ = google.auth.default(quota_project_id=PROJECT_ID)
    if args.teardown:
        teardown(args.model, creds)
    else:
        deploy(args.model, args.region, args.min_replica, args.max_replica, creds)


if __name__ == "__main__":
    main()
