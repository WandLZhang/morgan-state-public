#!/usr/bin/env python3
"""
Smoke-test + load-test a Morgan State Vertex endpoint (deployed by deploy.py).

The Model Garden dedicated endpoints take the Vertex "@requestFormat:
chatCompletions" wrapper (applies the chat template; returns an OpenAI-style
chat.completion under "predictions" with token usage). We measure with
non-streaming calls and derive throughput from usage.completion_tokens and
end-to-end latency.

Usage:
    source /home/user/Projects/.venv/bin/activate
    python bench.py --model gemma4 --smoke
    python bench.py --model gemma4 --qps 2 --duration 90 --in-tokens 1000 --out-tokens 1500

Reads endpoint-<model>.json (written by deploy.py).
"""
import argparse
import json
import os
import statistics
import subprocess
import sys
import threading
import time

import google.auth
import google.auth.transport.requests
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "wz-msu-test")


def load_info(model_key):
    p = os.path.join(HERE, f"endpoint-{model_key}.json")
    if not os.path.exists(p):
        sys.exit(f"ERROR: {p} not found — run deploy.py --model {model_key} first")
    with open(p) as f:
        return json.load(f)


def get_token():
    creds, _ = google.auth.default(quota_project_id=PROJECT_ID)
    creds.refresh(google.auth.transport.requests.Request())
    return creds.token


def project_number(info):
    if info.get("project_number"):
        return info["project_number"]
    if info.get("resource_name", "").startswith("projects/"):
        return info["resource_name"].split("/")[1]
    r = subprocess.run(["gcloud", "projects", "describe", info["project_id"],
                        "--format=value(projectNumber)"], capture_output=True, text=True)
    return r.stdout.strip()


def raw_predict_url(info):
    num, region, eid = project_number(info), info["region"], info["endpoint_id"]
    if info.get("dedicated_dns"):
        host = info["dedicated_dns"]
    else:
        host = f"{region}-aiplatform.googleapis.com"
    return f"https://{host}/v1/projects/{num}/locations/{region}/endpoints/{eid}:rawPredict"


def build_prompt(in_tokens, out_tokens):
    """about in_tokens of context + a directive that elicits about out_tokens of output."""
    ctx = ("Morgan State University runs a sovereign AI platform called Morgan State "
           "spanning research and instruction workloads on Google Cloud. ")
    words = int(in_tokens * 0.75)
    filler = " ".join((ctx * (words // len(ctx.split()) + 1)).split()[:words])
    return (filler + f"\n\nUsing the context above, write a thorough, detailed "
            f"technical overview (about {out_tokens} tokens) of how to serve large "
            f"language models cost-effectively on GPUs. Be comprehensive.")


def one_request(url, tok, prompt, max_tokens):
    payload = {
        "@requestFormat": "chatCompletions",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.7,
    }
    start = time.time()
    try:
        r = requests.post(url, json=payload, timeout=600, headers={
            "Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
        e2e = time.time() - start
        if r.status_code != 200:
            return {"ok": False, "status": r.status_code, "err": r.text[:300]}
        pred = r.json().get("predictions", {})
        choices = pred.get("choices", [])
        content = choices[0]["message"]["content"] if choices else ""
        usage = pred.get("usage", {}) or {}
        out_tok = usage.get("completion_tokens", 0)
        in_tok = usage.get("prompt_tokens", 0)
        return {"ok": True, "e2e": e2e, "out_tokens": out_tok, "in_tokens": in_tok,
                "tps": (out_tok / e2e if e2e > 0 else 0), "text": content}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "status": 0, "err": str(e)[:300]}


def smoke(info, max_tokens):
    url, tok = raw_predict_url(info), get_token()
    print(f"Endpoint {info['endpoint_id']} ({info['region']}) — {info['accelerator']}\n")
    r = one_request(url, tok, "In two sentences, what is Morgan State University known for?", max_tokens)
    if not r["ok"]:
        print(f"FAILED [{r['status']}]: {r['err']}")
        return False
    print(r["text"])
    print(f"\n[{r['out_tokens']} out tok | in {r['in_tokens']} | "
          f"{r['tps']:.1f} tok/s | e2e {r['e2e']:.1f}s]")
    return True


def load(info, qps, duration, in_tokens, max_tokens):
    url, tok = raw_predict_url(info), get_token()
    prompt = build_prompt(in_tokens, max_tokens)
    print(f"LOAD: {qps} QPS x {duration}s | inabout {in_tokens} out<={max_tokens} | "
          f"{info['accelerator']} ({info['model_id']})\n")
    results, threads, lock = [], [], threading.Lock()

    def fire():
        r = one_request(url, tok, prompt, max_tokens)
        with lock:
            results.append(r)

    t_end = time.time() + duration
    nxt = time.time()
    interval = 1.0 / qps
    launched = 0
    while time.time() < t_end:
        if time.time() >= nxt:
            t = threading.Thread(target=fire, daemon=True)
            t.start(); threads.append(t); launched += 1
            nxt += interval
        else:
            time.sleep(min(0.02, max(0, nxt - time.time())))
    for t in threads:
        t.join(timeout=600)

    ok = [r for r in results if r.get("ok")]
    fail = [r for r in results if not r.get("ok")]
    print(f"launched={launched}  ok={len(ok)}  fail={len(fail)}")
    if fail:
        print(f"  sample failure: [{fail[0].get('status')}] {fail[0].get('err','')[:200]}")
    if ok:
        e2e = sorted(r["e2e"] for r in ok)
        outs = [r["out_tokens"] for r in ok]
        tpss = [r["tps"] for r in ok]
        def pct(a, p): return a[min(len(a) - 1, int(len(a) * p))]
        print(f"  effective QPS (completed): {len(ok)/duration:.2f}")
        print(f"  E2E latency s : p50={pct(e2e,.5):.1f}  p95={pct(e2e,.95):.1f}  max={e2e[-1]:.1f}")
        print(f"  per-req tok/s : median={statistics.median(tpss):.1f}")
        print(f"  mean out tokens/req: {statistics.mean(outs):.0f}")
        print(f"  AGGREGATE output tok/s (system): {sum(outs)/duration:.0f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--qps", type=float, default=2.0)
    ap.add_argument("--duration", type=int, default=90)
    ap.add_argument("--in-tokens", type=int, default=1000)
    ap.add_argument("--out-tokens", type=int, default=1500)
    args = ap.parse_args()

    info = load_info(args.model)
    if args.smoke:
        smoke(info, args.out_tokens)
    else:
        load(info, args.qps, args.duration, args.in_tokens, args.out_tokens)


if __name__ == "__main__":
    main()
