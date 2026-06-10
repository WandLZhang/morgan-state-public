<!--
Copyright 2026 Google LLC

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    https://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
-->

# Setup (IT admin)

An H100-backed Colab Enterprise lab for 40 researchers in one sandbox project.

### 1. Create the sandbox project

### 2. Add attendees as editors

### 3. Run the preflight script
```bash
git clone https://github.com/WandLZhang/morgan-state-public.git
cd morgan-state-public
./setup/msu-sandbox-preflight.sh SANDBOX_PROJECT_ID                # fix what's broken
./setup/msu-sandbox-preflight.sh SANDBOX_PROJECT_ID --check-only   # audit only
```
It enables the 7 required APIs, ensures a default VPC exists, lifts the two org policies that block Colab runtime creation (`vmExternalIpAccess`, `requireShieldedVm`), **pre-creates the runtime templates** — `msu-h100` in us-east5 / us-central1 / us-west1, plus the fallback `msu-t4` in us-central1 (us-east5 offers no Colab GPU families besides H100) — flags location-restriction problems, and stages the notebook into the `SANDBOX_PROJECT-researcher-day` bucket for the import step. The notebook is downloaded from this repository at run time, so the bucket always gets the latest published copy; the cloned file is the fallback.
