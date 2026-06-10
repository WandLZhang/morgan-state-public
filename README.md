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

# Morgan State University × Google Cloud — Researcher Day

> 👋 **Welcome!** In the next hour you will run a Colab Enterprise notebook on your own **NVIDIA H100 GPU (80 GB)**, query real federal datasets with **BigQuery**, mount the lab's **Cloud Storage** bucket with **Cloud Storage FUSE**, run **Gemma 3** from **Vertex AI Model Garden** on your GPU, optionally deploy it to a production **Vertex AI endpoint**, and compare with Google's managed **Gemini** model. 🚀

---

1. 🔗 Open Colab Enterprise: https://console.cloud.google.com/vertex-ai/colab/notebooks and confirm the project picker (top bar) shows the sandbox project.

2. Open the **Runtimes** tab.

3. Set the region dropdown to **us-east5**.

4. Click **Create runtime** and select the runtime template **msu-h100**.

5. Name the runtime after yourself so people know who it belongs to.

6. Keep the remaining defaults and create it (about 5 minutes to boot).

7. 🛟 If creation fails with a capacity message, retry in 2-3 minutes, then walk the fallbacks in order:

   - Switch the region to **us-central1** and create the runtime from **msu-h100** there.

   - Switch the region to **us-west1** and create the runtime from **msu-h100** there.

   - Switch the region to **us-central1** and create the runtime from the **msu-t4** template.

8. Go to **My notebooks** and click **Import**.

9. Choose **Cloud Storage** and select the notebook from the `SANDBOX_PROJECT-researcher-day` bucket.

10. Open the notebook and click **Connect**, then pick the runtime you created.

11. ▶️ Run the cells top to bottom with the run button (or Shift+Enter).

## License

Apache 2.0 — see [LICENSE](LICENSE).

> **Disclaimer:** Education and event use only. The NHTSA and Census ACS datasets used here are fully public on `bigquery-public-data`.
