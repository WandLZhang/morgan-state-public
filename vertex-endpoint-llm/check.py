#!/usr/bin/env python3
"""
Preflight for the Morgan State Vertex endpoints. Confirms the three models are
deployable from Vertex AI Model Garden and that the project has RTX PRO 6000
serving quota in the target regions. Run this before deploy.py.

Usage:
    source /path/to/.venv/bin/activate
    GCP_PROJECT_ID=<your-project> python check.py
"""
import json
import os
import subprocess

PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "wz-msu-test")
REGIONS = os.environ.get("REGIONS", "us-central1,europe-west4,asia-southeast1").split(",")

# The Vertex / Model Garden SDK reads the ADC quota project, which can be stale,
# deleted, or unrelated — pin it explicitly.
os.environ.pop("GOOGLE_CLOUD_PROJECT", None)
os.environ.pop("GCLOUD_PROJECT", None)
os.environ["GOOGLE_CLOUD_QUOTA_PROJECT"] = PROJECT_ID

import google.auth  # noqa: E402
import vertexai  # noqa: E402
from vertexai import model_garden  # noqa: E402

MODELS = {
    "gemma4": "google/gemma4@gemma-4-26b-a4b-it",
    "llama33": "meta/llama3-3@llama-3.3-70b-instruct",
    "maverick": "meta/llama4@llama-4-maverick-17b-128e-instruct-fp8",
}


def check_models(creds):
    vertexai.init(project=PROJECT_ID, location=REGIONS[0], credentials=creds)
    for key, mid in MODELS.items():
        print(f"\n=== {key}: {mid} ===")
        try:
            for o in model_garden.OpenModel(mid).list_deploy_options():
                ms = getattr(getattr(o, "dedicated_resources", None), "machine_spec", None)
                if ms:
                    print(f"  {ms.machine_type:16s} {ms.accelerator_type} x{ms.accelerator_count}")
        except Exception as e:  # noqa: BLE001
            print("  ERROR:", str(e)[:200])


def check_quota():
    print("\n=== RTX PRO 6000 custom-model-serving quota ===")
    out = subprocess.run(
        ["gcloud", "alpha", "services", "quota", "list",
         "--service=aiplatform.googleapis.com", f"--consumer=projects/{PROJECT_ID}",
         "--filter=metric:custom_model_serving_nvidia_rtx_pro_6000_gpus", "--format=json"],
        capture_output=True, text=True)
    try:
        for item in json.loads(out.stdout or "[]"):
            for lim in item.get("consumerQuotaLimits", []):
                for b in lim.get("quotaBuckets", []):
                    r = b.get("dimensions", {}).get("region", "(default)")
                    if r in REGIONS or r == "(default)":
                        print(f"  {r:18s} limit={b.get('effectiveLimit', '0')}")
    except Exception:
        print(out.stdout[:400] or out.stderr[:400])


if __name__ == "__main__":
    print(f"Project: {PROJECT_ID} | regions: {', '.join(REGIONS)}")
    creds, _ = google.auth.default(quota_project_id=PROJECT_ID)
    check_models(creds)
    check_quota()
