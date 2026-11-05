# SENTINEL Demo

These are my notes for demoing SENTINEL, my self-healing infrastructure project.
I wrote down how I set it up, what I show, what I say at each step, what has gone
wrong, and how I reset everything between runs.

Here is the whole demo in one table:

| Step | Command hits | What it proves |
|---|---|---|
| 1. Baseline | `predictor /risk` | The "before" state |
| 2. Break it | `inject_memory_leak.py` | A real, unbounded memory leak, not a fake metric |
| 3. Predictor notices | `predictor /alerts` | Detection compares against a rolling baseline, not a hardcoded limit |
| 4. Diagnosis | `diagnosis-agent /diagnoses` | A local LLM explains the cause, grounded in one matched runbook |
| 5. Action | `remediator /remediations` | Safe fixes run on their own and get verified; risky ones wait for a human |
| 6. One record | `api /incidents/latest` | Three services' views of one incident, joined into one timeline |
| 7. Grafana | Incident Timeline dashboard | The same story, visually |

The walkthrough takes about 10 minutes. On a cluster that's already built, I need
about 20 minutes of preparation before it.

## Part 1: First-time setup

I only need this part when the cluster doesn't exist yet. To check:

```bash
kubectl -n argocd get application sentinel   # want: Synced  Healthy
kubectl -n sentinel get pods                 # want: all Running
```

### 1.1 Python environment

My chaos scripts use `httpx`, which the system Python doesn't have. A bare shell
may not even have a `python` command until the venv is active.

```bash
python3 -m venv venv   # skip if venv/ already exists
source venv/bin/activate
pip install -r requirements.txt pytest-cov black pylint httpx anyio
```

### 1.2 Cluster and services

```bash
make apply && make bootstrap        # Kind cluster + Argo CD, about 1 min
make build && make load             # all 6 images, several min the first time
kubectl -n argocd get application sentinel   # wait for Synced + Healthy
```

Argo CD deploys everything from `infra/k8s` in Git. Kind can't pull images that
were only built locally, so `make load` copies them into the cluster.

### 1.3 The LLM model

The model isn't baked into the Ollama image, so I pull it once:

```bash
kubectl -n sentinel exec deploy/ollama -- ollama pull llama3.2:1b   # 1-2 min
```

### 1.4 Slack (needed for the approval path)

I created a Slack app at <https://api.slack.com/apps> with these bot scopes:
`chat:write`, `channels:read`, `channels:join`. Its credentials don't live in Git,
so I have to store them again after every cluster rebuild:

```bash
kubectl -n sentinel create secret generic remediator-slack \
  --from-literal=bot-token='xoxb-...' \
  --from-literal=signing-secret='...'
kubectl -n sentinel rollout restart deployment/remediator
```

The channel is a public one named `#sentinel-incidents`. The remediator joins it on
startup, so `/invite` isn't needed. If its logs show `failed to auto-join slack
channel`, I run `/invite @your-bot` in the channel instead.

## Part 2: What I do right before presenting

### 2.1 Reset to a clean slate

Every service keeps its history in memory except `api`, which uses SQLite. After a
few practice runs, the Incident Timeline fills up with old incidents and becomes
unreadable, so I clear it.

I restart one service at a time. If they all restart together, a new pod can read
stale data from an upstream pod that hasn't terminated yet.

```bash
kubectl -n sentinel rollout restart deployment/predictor
kubectl -n sentinel rollout status deployment/predictor --timeout=60s

kubectl -n sentinel rollout restart deployment/diagnosis-agent
kubectl -n sentinel rollout status deployment/diagnosis-agent --timeout=60s

kubectl -n sentinel rollout restart deployment/remediator
kubectl -n sentinel rollout status deployment/remediator --timeout=60s

# api last, and wipe its database
kubectl -n sentinel exec deploy/api -- rm -f /data/incidents.db
kubectl -n sentinel rollout restart deployment/api
kubectl -n sentinel rollout status deployment/api --timeout=60s
```

### 2.2 Start the port-forwards

This comes after the reset, because restarting a pod kills any port-forward attached
to it. I clear the old ones first: a leftover port-forward keeps its port even after
its pod is gone, which causes `address already in use`.

```bash
pkill -f "kubectl.*port-forward"
sleep 1
kubectl -n sentinel port-forward svc/demo-api 18080:8080 &
kubectl -n sentinel port-forward svc/predictor 18001:8080 &
kubectl -n sentinel port-forward svc/diagnosis-agent 18002:8080 &
kubectl -n sentinel port-forward svc/remediator 18003:8080 &
kubectl -n sentinel port-forward svc/api 18004:8080 &
kubectl -n sentinel port-forward svc/grafana 18030:3000 &
```

Then I check that the slate is clean:

```bash
curl localhost:18004/api/v1/incidents   # expect {"incidents":[]}
```

### 2.3 Wait for the baseline to fill

**I wait at least 2 minutes after the reset, ideally 5.** The predictor can't score
anything until it has 8 samples (15 s apart, so 2 min), and its full window is 20
samples (5 min). A leak injected too early won't raise an alert.

### 2.4 Warm up the LLM

The first call after the model loads is slow, so I load it directly within 5 minutes
of going live (Ollama unloads idle models after about 5 minutes by default):

```bash
kubectl -n sentinel exec deploy/ollama -- ollama run llama3.2:1b "Say ready."
```

**I don't warm up with `POST /diagnose`.** That result goes into the real pipeline:
the remediator picks it up as a new diagnosis and can restart `demo-api` before the
demo has even started.

### 2.5 What I keep open

- A terminal with the venv active: `source venv/bin/activate`
- Grafana at <http://localhost:18030> (`admin` / `admin`), Incident Timeline
- Slack, in `#sentinel-incidents`
- The recorded video, as a backup in case the live demo fails

## Part 3: The live walkthrough

### Step 1: Baseline

```bash
curl localhost:18001/risk | python3 -m json.tool
```

I point at `overall_risk` and the four metrics: `cpu_percent`, `memory_bytes`,
`latency_seconds`, `error_rate`.

> "This is the before state. SENTINEL is watching four signals on my demo service."

**I check this output before saying it's all clear.** An idle service can show
`"alerting": true`. Its numbers are so small and steady that a tiny wobble gives a
high z-score. For example, I've seen CPU at 0.44% score z = 5.4, which puts
`overall_risk` above 1. When that happens, I just say so:

> "CPU is flagged, but look at the value: under 1%. A statistical detector is
> sensitive when a service is idle. It's a known limitation of the simple baseline."

### Step 2: Break it

```bash
python scripts/chaos/inject_memory_leak.py --base-url http://localhost:18080 --chunk-mb 30 --steps 10
```

Each step adds 30 MB every 15 s, which gives me time to talk.

> "This is a real bug pattern: a slow leak with no plateau, the kind that
> eventually gets a pod OOM-killed in production."

`demo-api` has a 256 MiB limit, so without a fix it would die at about step 7.

**The script may stop with a connection error partway through.** That's actually a
good sign: SENTINEL restarted the pod, which killed the port-forward. I just restart
it:

```bash
kubectl -n sentinel port-forward svc/demo-api 18080:8080 &
```

### Step 3: The predictor noticed

```bash
curl localhost:18001/alerts | python3 -m json.tool
```

I point at the newest `memory_bytes` entry and its `z_score`.

> "Nobody told it what normal is. It compares each value to a rolling mean and
> standard deviation, and alerts at 3 sigma. There's a cooldown, so one leak fires
> one alert, not one per poll."

### Step 4: The diagnosis

This shows up 30-50 seconds after the alert.

```bash
curl localhost:18002/diagnoses | python3 -m json.tool
```

I read out `root_cause` and `recommended_action` from the newest entry and point at
`runbook_id`.

> "This took 30-50 seconds because it's a small LLM running on CPU. The model only
> sees the runbook matched to this metric. If no runbook covers the metric, it
> isn't asked at all."

### Step 5: It fixes it, or asks a human

```bash
curl localhost:18003/remediations | python3 -m json.tool
```

I look for the entry with `"auto": true`, `"status": "resolved"` and `"result":
"restarted deployment/demo-api"`.

> "That's a real Kubernetes API call from a least-privilege service account. Then
> a health check confirmed it worked: resolved, not just executed."

Then I explain the rule: an action runs automatically only if the runbook allows it
**and** the recommended action names restart, scale or rollback. Everything else
goes to Slack. Part 4 shows that path live.

### Step 6: One record

```bash
curl localhost:18004/api/v1/incidents/latest | python3 -m json.tool
```

I trace `predicted_at`, `diagnosed_at` and `remediated_at`, then `stage`, `status`
and `verification_status`.

> "Each service only knows its own piece. This joins them into one incident, and
> it's the only history that survives a restart."

### Step 7: Grafana

I open **Incident Timeline** at <http://localhost:18030>. There's one row per
incident, coloured by stage.

> "Same story as that JSON, but this is what an on-call engineer would actually
> look at."

## Part 4: The Slack approval path

Memory and CPU faults usually take the automatic path. To show a human approval, I
use latency, because two of its three runbooks don't allow automatic action.

### 4.1 Making the message appear

```bash
python scripts/chaos/inject_latency.py --base-url http://localhost:18080 --delay-ms 800 --duration-seconds 90
```

In a second terminal, I send traffic. The delay only applies to real requests, so
without traffic no latency reaches Prometheus:

```bash
for i in $(seq 1 30); do curl -s -o /dev/null http://localhost:18080/; sleep 2; done
```

After 30-60 s for the alert, plus diagnosis time:

```bash
curl localhost:18003/remediations | python3 -m json.tool
```

I look for `"auto": false, "status": "awaiting_approval"`. The Approve/Deny message
should now be in `#sentinel-incidents`.

### 4.2 Making the buttons work

The message appears without this, but a click needs a public URL to reach.

**Terminal 1** (stays running; forwards the remediator to port 8082):

```bash
./scripts/slack_tunnel.sh
```

**Terminal 2** (stays running; prints a `https://....trycloudflare.com` URL):

```bash
cloudflared tunnel --url http://localhost:8082
```

**In Slack:** api.slack.com/apps → my app → **Interactivity & Shortcuts** → turn it
on → set **Request URL** to `https://<tunnel-url>/slack/interactions` → **Save
Changes**.

The URL changes every time the tunnel restarts. I have to update it in Slack each
time, or clicks silently go nowhere.

### 4.3 Reading the message before clicking Approve

**Known bug in my classifier: I read `action_text` first.** The classifier looks for
the word "restart" and doesn't understand "do not". The
`latency-cold-cache-thundering-herd` runbook says "Do not restart or scale...", but
it's classified as `restart`, so **clicking Approve on it really does restart
`demo-api`**. In the demo, I click **Deny** on that one, or use a message that truly
recommends the action.

### 4.4 Other faults

| Script | Usual result |
|---|---|
| `inject_memory_leak.py` | Automatic restart. Best for the main demo |
| `inject_cpu_spike.py --base-url ... --duration-seconds 60 --workers 2` | Usually automatic |
| `inject_latency.py` | Often Slack approval, depending on the matched runbook. Needs traffic |
| `inject_error_rate.py` | **I avoid this one.** Injected 500s return before the metrics middleware records them, so the predictor never sees them |

To watch risk live, or to clear all injected faults:

```bash
python scripts/chaos/watch.py --predictor-url http://localhost:18001
python scripts/chaos/reset.py --base-url http://localhost:18080
```

## Part 5: If something breaks live

| Problem | What I do |
|---|---|
| A port-forward died | Expected after a pod restart. I re-run it: `kubectl -n sentinel port-forward svc/<name> <port>:8080` (Grafana is `:3000`) and carry on |
| `python` or `httpx` not found | Run `source venv/bin/activate` |
| No alert after the leak | The baseline probably hadn't filled, or a recent alert is in its 120 s cooldown. I check `samples` in `/risk` |
| Diagnosis is slow | It's real CPU inference, and I say so |
| No Slack message | Check `kubectl -n sentinel logs deploy/remediator --tail=50 \| grep -i slack` |
| Slack buttons do nothing | The tunnel URL changed, so I update it in Slack |
| Timeline is cluttered | Run the reset in section 2.1 |
| Nothing works | Play the recorded video and explain over it |

## Part 6: Questions I expect from the panel

My plan for these is to state the real limitation plainly, say why it's there, and
say what would remove it. I think that's better than hiding a gap.

**"Is this really autonomous, or did you trigger it?"**
The diagnosis-agent and remediator run their own background poll loops, whether or
not anyone runs a command. My `curl` commands only read results.

**"Why `llama3.2:1b`?"**
It's the smallest model I tested that reliably reasons about a runbook on CPU only.
`tinyllama` just echoed the prompt back.

**"How do you stop the LLM making things up?"**
It only gets one runbook matched to the alerting metric, and its output is forced
into a fixed JSON format. With no matching runbook it's never called.

**"What are the limits of the detector?"**
It's simple and explainable, but slow drifts can be missed because the baseline
drifts along with the fault. It can also false-alarm on an idle service. A
trend-aware model is my next step.

**"Can the safety rule be fooled?"**
Yes, and I know how. It matches keywords, so "do not restart" counts as "restart".
The fix is to choose the action from the runbook's own `safe_actions` list instead of
parsing LLM text.

**"Does CI deploy automatically?"**
Not fully. CI lints, tests and builds images, but nothing moves a new image tag into
the Git manifests yet. `scripts/promote-image.sh` does that by hand.

**"Is it on the cloud?"**
Not yet. I've written and validated Terraform for GKE, AKS and EKS
(`infra/terraform-gke`, `infra/terraform-azure`, `infra/terraform-aws`), but none of
it has been applied, because of cloud account verification. `make gke-apply`, `make
azure-apply` and `make aws-apply` are the commands.

## Part 7: Full teardown and rebuild

I only do this if the cluster is badly broken, and I try the reset in section 2.1
first. **This deletes the cluster and every Secret in it, including the Slack
credentials.**

```bash
pkill -f "kubectl.*port-forward"
make destroy
./scripts/run_jenkins.sh stop                # optional
# docker volume rm sentinel_jenkins_home     # only to wipe Jenkins completely
```

Then I repeat Part 1, including the Slack secret in section 1.4.
