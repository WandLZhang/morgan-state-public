#!/usr/bin/env bash
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# msu-sandbox-preflight.sh — make the shared sandbox project ready for the MSU researcher day H100 lab.
#
# What it fixes (each was hit and verified during rehearsal on 2026-06-10):
#   1. Required APIs disabled on fresh projects
#   2. Missing default VPC            -> Colab runtime creation fails: "networks/default cannot be found"
#   3. compute.vmExternalIpAccess     -> runtime fails: "Constraint ... violated"
#   4. compute.requireShieldedVm      -> runtime fails: "Secure Boot is not enabled"
# Plus warnings for: gcp.resourceLocations blocking us-east5, and the two H100 quotas to eyeball.
#
# Usage:
#   ./msu-sandbox-preflight.sh SANDBOX_PROJECT                 # check, and fix what's broken (run once)
#   ./msu-sandbox-preflight.sh SANDBOX_PROJECT --check-only    # audit only, change nothing
#   ./msu-sandbox-preflight.sh SANDBOX_PROJECT --reserve N ["projA,projB"]   # book N H100s for the event
#                                                # (share list only needed if consumers are OTHER projects)
#
# Permissions: API/VPC fixes need project owner/editor. Org-policy overrides need
# roles/orgpolicy.policyAdmin (granted at org level — this script is for IT/admins, not researchers).
set -euo pipefail

REGION="us-east5"
ZONE="${MSU_RESERVATION_ZONE:-us-east5-a}"
H100_REGIONS="${MSU_H100_REGIONS:-us-east5 us-central1 us-west1}"

PROJECT="${1:?usage: $0 PROJECT_ID [--check-only | --reserve N \"proj1,proj2\"]}"
MODE="${2:-}"

say()  { printf '%s\n' "$*"; }
ok()   { printf '  [OK]    %s\n' "$*"; }
fix()  { printf '  [FIXED] %s\n' "$*"; }
warn() { printf '  [WARN]  %s\n' "$*"; }

# ---------------------------------------------------------------- reserve mode
if [ "$MODE" = "--reserve" ]; then
  COUNT="${3:?--reserve needs a VM count}"
  SHARE_WITH="${4:-}"
  say "Booking $COUNT x a3-highgpu-1g (1x H100 80GB each) in $ZONE, project $PROJECT"
  say "Cost while held: about \$11/hr per VM. Delete after the event:"
  say "  gcloud compute reservations delete msu-researcher-day --project=$PROJECT --zone=$ZONE"
  if [ -n "$SHARE_WITH" ]; then
    say "Sharing with: $SHARE_WITH (requires same org + compute.sharedReservationsOwnerProjects permitting $PROJECT)"
    gcloud compute reservations create msu-researcher-day \
      --project="$PROJECT" --zone="$ZONE" \
      --machine-type=a3-highgpu-1g --vm-count="$COUNT" \
      --share-setting=projects --share-with="$SHARE_WITH"
  else
    gcloud compute reservations create msu-researcher-day \
      --project="$PROJECT" --zone="$ZONE" \
      --machine-type=a3-highgpu-1g --vm-count="$COUNT"
  fi
  say "Done. Matching runtimes in the sandbox project consume this automatically."
  exit 0
fi

CHECK_ONLY=0
[ "$MODE" = "--check-only" ] && CHECK_ONLY=1

say "Preflight for project: $PROJECT  (mode: $([ $CHECK_ONLY -eq 1 ] && echo check-only || echo check+fix))"

# ---------------------------------------------------------------- 1. APIs
say "1) Required APIs"
ENABLED=$(gcloud services list --enabled --project="$PROJECT" --format="value(config.name)")
for API in aiplatform.googleapis.com dataform.googleapis.com compute.googleapis.com \
           bigquery.googleapis.com bigquerystorage.googleapis.com storage.googleapis.com \
           orgpolicy.googleapis.com; do
  case "$ENABLED" in
    *"$API"*) ok "$API" ;;
    *) if [ $CHECK_ONLY -eq 1 ]; then warn "$API not enabled"; else
         gcloud services enable "$API" --project="$PROJECT" >/dev/null
         fix "$API enabled"
       fi ;;
  esac
done

# ---------------------------------------------------------------- 2. default VPC
say "2) Default VPC"
if gcloud compute networks describe default --project="$PROJECT" --format="value(name)" >/dev/null 2>&1; then
  ok "network 'default' exists"
else
  if [ $CHECK_ONLY -eq 1 ]; then warn "no 'default' network — Colab runtime creation WILL fail"; else
    gcloud compute networks create default --subnet-mode=auto --project="$PROJECT" >/dev/null
    fix "created auto-mode 'default' network"
  fi
fi

# ---------------------------------------------------------------- 3. external IP policy
say "3) Org policy: compute.vmExternalIpAccess"
EXT_EFFECTIVE=$(gcloud org-policies describe compute.vmExternalIpAccess --project="$PROJECT" --effective --format="yaml(spec.rules)" 2>/dev/null || true)
case "$EXT_EFFECTIVE" in
  *allowAll:\ true*|"")
    ok "external IPs allowed (effective policy permits, or no policy set)"
    ;;
  *)
    if [ $CHECK_ONLY -eq 1 ]; then
      warn "external IPs restricted — Colab runtime creation WILL fail. Effective rules: ${EXT_EFFECTIVE}"
    else
      gcloud org-policies set-policy /dev/stdin >/dev/null <<EOF
name: projects/$PROJECT/policies/compute.vmExternalIpAccess
spec:
  rules:
  - allowAll: true
EOF
      fix "project-level override: vmExternalIpAccess allowAll"
    fi
    ;;
esac

# ---------------------------------------------------------------- 4. shielded VM policy
say "4) Org policy: compute.requireShieldedVm"
SHV_EFFECTIVE=$(gcloud org-policies describe compute.requireShieldedVm --project="$PROJECT" --effective --format="yaml(spec.rules)" 2>/dev/null || true)
case "$SHV_EFFECTIVE" in
  *enforce:\ true*)
    if [ $CHECK_ONLY -eq 1 ]; then
      warn "Shielded VM enforced — Colab runtime creation WILL fail"
    else
      gcloud org-policies set-policy /dev/stdin >/dev/null <<EOF
name: projects/$PROJECT/policies/compute.requireShieldedVm
spec:
  rules:
  - enforce: false
EOF
      fix "project-level override: requireShieldedVm not enforced"
    fi
    ;;
  *)
    ok "Shielded VM not enforced"
    ;;
esac

# ---------------------------------------------------------------- 5. location restriction (warn only)
say "5) Org policy: gcp.resourceLocations (lab region is $REGION)"
LOC_EFFECTIVE=$(gcloud org-policies describe gcp.resourceLocations --project="$PROJECT" --effective --format="yaml(spec.rules)" 2>/dev/null || true)
if [ -z "$LOC_EFFECTIVE" ]; then
  ok "no location restriction"
else
  warn "location restriction present — confirm it permits $REGION. Effective rules:"
  printf '%s\n' "$LOC_EFFECTIVE"
fi

# ---------------------------------------------------------------- 6. H100 runtime templates
# Pre-creating these lets researchers skip the curl in the notebook's Section 1 (the gcloud
# 'runtimes create' line and the console Connect dialog find them by id 'msu-h100').
# H100 isn't in the console/gcloud template enums yet, hence the REST call.
say "6) H100 runtime templates (regions: $H100_REGIONS; templates are free)"
for R in $H100_REGIONS; do
  if gcloud colab runtime-templates describe msu-h100 --region="$R" --project="$PROJECT" --format="value(name)" >/dev/null 2>&1; then
    ok "msu-h100 exists in $R"
  else
    if [ $CHECK_ONLY -eq 1 ]; then warn "msu-h100 template missing in $R"; else
      HTTP=$(curl -s -o /tmp/preflight-tpl-resp.json -w '%{http_code}' -X POST \
        -H "Authorization: Bearer $(gcloud auth print-access-token)" -H "Content-Type: application/json" \
        "https://$R-aiplatform.googleapis.com/v1beta1/projects/$PROJECT/locations/$R/notebookRuntimeTemplates?notebookRuntimeTemplateId=msu-h100" \
        -d '{"displayName":"msu-h100","machineSpec":{"machineType":"a3-highgpu-1g","acceleratorType":"NVIDIA_H100_80GB","acceleratorCount":1},"dataPersistentDiskSpec":{"diskType":"pd-balanced","diskSizeGb":"100"},"networkSpec":{"enableInternetAccess":true}}')
      if [ "$HTTP" = "200" ]; then
        fix "created msu-h100 template in $R"
      else
        warn "template create failed in $R (HTTP $HTTP):"
        cat /tmp/preflight-tpl-resp.json
      fi
    fi
  fi
done

# ---------------------------------------------------------------- 6b. fallback GPU templates (us-central1)
# us-east5 offers no Colab GPU families besides H100 (g2/n1/a2 all rejected there, verified),
# so the T4 fallback lives in us-central1. Using one means re-importing the notebook
# with region us-central1 first (runtimes only appear in the notebook's own region).
say "6b) Fallback GPU template in us-central1 (T4)"
if gcloud colab runtime-templates describe msu-t4 --region=us-central1 --project="$PROJECT" --format="value(name)" >/dev/null 2>&1; then
  ok "msu-t4 exists in us-central1"
else
  if [ $CHECK_ONLY -eq 1 ]; then warn "msu-t4 template missing in us-central1"; else
    gcloud colab runtime-templates create --region=us-central1 --project="$PROJECT" \
      --display-name="msu-t4" --runtime-template-id=msu-t4 \
      --machine-type=n1-standard-8 --accelerator-type=NVIDIA_TESLA_T4 --accelerator-count=1 >/dev/null 2>&1
    fix "created msu-t4 template in us-central1"
  fi
fi

# ---------------------------------------------------------------- 6c. lab bucket + notebook staging
# Researchers import the notebook from this bucket (Import -> Cloud Storage). One bucket
# for the whole event: the notebook sits at the root, researcher folders are created beside it.
# The notebook is downloaded from the public repo at run time so the bucket always gets the
# latest published copy even if this clone is stale; the repo-local file is the offline fallback.
say "6c) Lab bucket + notebook staging"
LAB_BUCKET="$PROJECT-researcher-day"
NOTEBOOK_URL="https://raw.githubusercontent.com/WandLZhang/morgan-state-public/main/msu-researcher-day.ipynb"
NOTEBOOK_LOCAL="$(cd "$(dirname "$0")" && pwd)/../msu-researcher-day.ipynb"
if gcloud storage buckets describe "gs://$LAB_BUCKET" --format="value(name)" >/dev/null 2>&1; then
  ok "bucket gs://$LAB_BUCKET exists"
else
  if [ $CHECK_ONLY -eq 1 ]; then warn "bucket gs://$LAB_BUCKET missing"; else
    gcloud storage buckets create "gs://$LAB_BUCKET" --location="$REGION" --uniform-bucket-level-access --project="$PROJECT" >/dev/null
    fix "created gs://$LAB_BUCKET"
  fi
fi
NOTEBOOK_SRC=""
if curl -fsSL "$NOTEBOOK_URL" -o /tmp/msu-researcher-day.ipynb; then
  NOTEBOOK_SRC="/tmp/msu-researcher-day.ipynb"
  ok "downloaded the latest notebook from $NOTEBOOK_URL"
elif [ -f "$NOTEBOOK_LOCAL" ]; then
  NOTEBOOK_SRC="$NOTEBOOK_LOCAL"
  warn "GitHub download failed — using the local copy at $NOTEBOOK_LOCAL (git pull to be sure it is current)"
fi
if [ -z "$NOTEBOOK_SRC" ]; then
  warn "no notebook available — stage it manually: gcloud storage cp msu-researcher-day.ipynb gs://$LAB_BUCKET/"
elif [ $CHECK_ONLY -eq 1 ]; then
  ok "would stage $NOTEBOOK_SRC to gs://$LAB_BUCKET/"
else
  gcloud storage cp "$NOTEBOOK_SRC" "gs://$LAB_BUCKET/msu-researcher-day.ipynb" >/dev/null
  fix "staged msu-researcher-day.ipynb to gs://$LAB_BUCKET/"
fi

# ---------------------------------------------------------------- 7. quotas (eyeball list)
say "7) Quotas to REQUEST for a shared sandbox project (everyone draws from these):"
say "   - GPUS_PER_GPU_FAMILY (H100 family), $REGION: >= concurrent attendees (e.g. 40);"
say "     fresh-project seeding is far below that (us-west1 even defaults to 0)"
say "   - Regional CPUS, $REGION: >= 26 x attendees (each a3-highgpu-1g carries 26 vCPUs)"
say "   - Custom model serving Nvidia H100 GPUs, $REGION: default 16, shared by the room (Section 6 is optional)"
say "   https://console.cloud.google.com/iam-admin/quotas?project=$PROJECT"

say ""
say "Preflight complete."
