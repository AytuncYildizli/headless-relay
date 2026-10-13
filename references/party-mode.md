# Party Mode / Council Mode

Party Mode is the explicit **ask everyone who is safely available** workflow. The orchestrator preflights every built-in lane plus every valid custom target, gives each admitted lane the same canonical user brief, then synthesizes agreement, dissent, and evidence without treating majority vote as truth. This is a skill/protocol for the parent harness, not an executable council dispatcher or an automatically enforced security boundary.

## Triggers

Enter Party Mode only when the user explicitly asks for it, for example:

- `party mode`
- `council mode`
- `ask everyone` / `ask every model`
- `run all available models`
- `her şeyi dene` / `hepsine sor`

Do not turn a routine “second opinion” request into Party Mode. It consumes more quota, time, and local compute than a targeted relay.

## Contract

1. **Freeze one brief.** Write the complete question and allowed context to one prompt file, normalize once as below, then freeze the canonical user brief.
2. **Build the candidate roster.** Include every built-in lane and every syntactically valid entry in `~/.agents/relay-targets.json`. This means lanes, not every model in each catalog; OpenCode/ZCode are alternative GLM transports, not extra votes. Reject invalid registry entries with a reason; use unique path-safe artifact IDs, not unchecked target names.
3. **Apply gates before invocation.** For every candidate, check its actual transport availability/auth, the same-provider/native-subagent rule, provider terms, and task/data-egress permission. Native transport availability is a harness capability check, not a demand for the provider's CLI binary.
4. **Admit all safe and available lanes.** “Everyone” means all lanes that pass the gates. Record unavailable or policy-blocked lanes with a short reason. Never install a binary, log in, rotate auth, or silently substitute another model to make the roster look full.
5. **Schedule by resource class.** Parallelize independent cloud/CLI lanes that are safe together. Run Antigravity sequentially because of its documented burst hang. Run heavyweight local custom targets sequentially unless their registry notes explicitly say concurrent execution is safe. Never saturate the parent machine just to maximize lane count.
6. **Capture one artifact per lane.** Keep the canonical brief, separate bounded output/status artifacts and a manifest. Native subagents require their own independent receipt, too. A failed lane must not erase successful outputs. Inspect transport status and structured error fields; a nonempty stdout file alone is not a usable answer.
7. **Synthesize as the parent.** Report shared findings, unique findings by lane, direct contradictions, and unresolved questions. Preserve minority dissent. A majority vote is not evidence.
8. **Verify before promoting claims.** Concrete file:line, command, benchmark, or source claims outrank vague agreement, but still require verification through the parent's tools or primary sources.

## Canonical user brief

- Normalize the allowed user task/context once by removing trailing LF bytes, then freeze that canonical UTF-8 user payload for every admitted lane; never shorten or improve it per model.
- This promises the same canonical user brief, not identical total model context; harness/system/tool instructions differ. Raw command substitution removes trailing newlines, so it does not preserve arbitrary source-file bytes.
- Send the canonical file through stdin or a quoted argv adapter, and the same user payload through native subagent transport; wrappers may add transport/safety instructions but must not rewrite the user brief.

A text brief must be valid UTF-8, contain no NUL bytes (argv cannot carry NUL), and remain nonempty after normalization. Reject unsuitable input instead of silently altering it further. Normalize **once**, before dispatch; do not normalize each model's copy differently. For example, after creating the private directory below:

```bash
python3 - /absolute/path/to/handoff.md "$run_dir/brief.md" <<'PY'
from pathlib import Path
import sys
payload = Path(sys.argv[1]).read_bytes().rstrip(b"\n")
payload.decode("utf-8")
if not payload or b"\0" in payload:
    raise SystemExit("brief must be nonempty UTF-8 text without NUL")
Path(sys.argv[2]).write_bytes(payload)
PY
chmod 600 "$run_dir/brief.md"
# stdin: < "$run_dir/brief.md"
# argv:  "$(cat "$run_dir/brief.md")"  (already normalized, quoted)
```

This is payload preparation, not a new dispatcher. Keep all existing safe adapters and provider gates. For Grok, send this payload through `grok_relay`; never bypass its safety instructions or helper to force byte equality.

## Roster receipt

Before invoking, persist each candidate's admission state separately from its transport:

- `admitted` — transport available and all gates passed
- `unavailable` — required transport, endpoint, model, or auth missing
- `blocked_policy` — provider terms or task policy forbids the handoff
- `blocked_egress` — the lane cannot safely receive the requested context
- Same-provider lanes MUST be admitted with `transport=native_subagent` when the harness supplies that transport and all gates pass; invoke them with the canonical user brief and require an independent output/error receipt.
- If the harness lacks native subagent transport, mark that lane `unavailable` with a reason; do not call its same-provider headless CLI as a fallback.

Do not use `excluded_same_provider`: avoiding the CLI is a transport choice, not permission to omit a safely available native participant. Record actual provider/model identity when known; if the harness does not reveal the model, record `harness_default_unreported` rather than inventing one. Do not count duplicated transport aliases or the parent's own synthesis as independent participants.

Minimal illustrative terminal manifest (fictional lane records, not a live run):

```json
{
  "bookkeeping": "complete",
  "outcome": "degraded",
  "lanes": [
    {"lane": "gpt", "provider": "openai", "model": "harness_default_unreported", "transport": "native_subagent", "state": "admitted", "terminal": "output", "artifact": "answers/gpt.md", "reason": null},
    {"lane": "glm", "provider": "zai", "model": "selected-model-id", "transport": "headless_cli", "state": "admitted", "terminal": "timeout", "artifact": "status/glm.json", "reason": "bounded deadline exceeded"},
    {"lane": "gemini", "provider": "google", "model": "requested-model-id", "transport": "none", "state": "unavailable", "terminal": "not_invoked", "artifact": null, "reason": "required transport unavailable"}
  ]
}
```

Real manifests must enumerate the full roster, not just these three examples. Terminal values are `output`, `error`, `timeout` for admitted lanes and `not_invoked` for skipped lanes. Output receipts identify the answer artifact; error/timeout receipts identify a bounded status artifact, even if no answer was produced. Record the chosen timeout, exit/error status, usable-answer assessment, and started/finished timestamps in those receipts. Paths are relative to the private run directory. Absence of model identity is reported, never presented as an exact-model guarantee.

If fewer than two independent lanes can be admitted, proceed only when the user explicitly asked to use whatever is available; otherwise ask whether a single-lane answer is useful. Zero admitted lanes yields `failure`, not a successful council. If a larger roster later returns only one usable answer, preserve it and report **degraded Party Mode**.

## Run directory

- Create a fresh private run directory with mode 700 and brief/artifact files with mode 600; these permissions do not isolate processes sharing the same UID.
- Never persist credentials, raw auth output, or secret-bearing environment dumps in the manifest or lane receipts; redact secret-bearing stdout/stderr before persistence and apply the user's retention/cleanup policy.

```bash
umask 077
run_dir=$(mktemp -d "${TMPDIR:-/tmp}/headless-party.XXXXXX")
chmod 700 "$run_dir"
mkdir "$run_dir/answers" "$run_dir/status"
# Prepare brief.md using the canonicalization example above.
```

Keep `brief.md`, `manifest.json`, `answers/<safe-lane-id>.md`, `status/<safe-lane-id>.json`, and `synthesis.md` inside this directory. Do not persist unredacted raw stdout/stderr as a workaround. Bound capture sizes before dispatch and keep temporary raw buffers private until redaction/cleanup. A private directory does not make cloud inference local or waive user data-egress consent.

## Scheduling rules

- Start compatible parallel lanes using the exact safe adapters from `SKILL.md`; collect per-lane status, not the exit status of a bare `wait`.
- Wait for that burst to finish before running Antigravity.
- Run heavyweight local custom targets one at a time unless target notes explicitly permit concurrency.
- Give each admitted lane, including native subagents, a bounded timeout chosen before dispatch; persist timeout/error receipts and preserve successful sibling artifacts. Never retry indefinitely.
- Do not run Grok in the repository. Pass only the canonical user payload through `grok_relay`.
- Do not grant repository, network, or parent tool permissions merely because Party Mode was requested; pass only allowed context and retain each transport's least-privilege safety contract.

The parent must use bounded harness cancellation/lifecycle facilities appropriate to each transport. These instructions do not ship process supervision for arbitrary lanes. The older hand-picked shell burst in `SKILL.md` is not a Party receipt collector or an aggregate success check.

## Synthesis format

Report:

- **Roster**: admission state, provider/model/transport, terminal result or skip reason, receipt path.
- **Bookkeeping and useful outcome**: `complete`/`incomplete` separately from `success`/`degraded`/`failure`, with usable independent answer count.
- **Shared findings**: supporting lanes and parent verification receipt.
- **Unique findings and dissent**: lane, evidence or unverified status.
- **Contradictions**: opposing claims, what was checked, current verdict.
- **Parent verdict**: recommendation, confidence and unresolved risks; no answer is manufactured for a failed lane.

## Completion and useful outcome

- Bookkeeping is `complete` only if the canonical brief exists, the full roster was evaluated, every skipped lane has a reason, and every admitted lane (including native subagents) has a terminal output/error receipt.
- A missing receipt or nonterminal lane makes bookkeeping `incomplete`, never GREEN, even when other lanes answered.
- With zero usable independent answers, the outcome is `failure`; complete bookkeeping does not imply useful success.
- With one usable independent answer, or any failed/unavailable/blocked candidate, the outcome is `degraded`; count native and external lanes equally, and never count the parent synthesis as an independent answer.
- The outcome is `success` only with at least two usable independent answers and no failed/unavailable/blocked candidates; this is participation success, not proof that the claims are true.

An answer is usable only after checking the transport's terminal status, structured error flags, and nonempty substantive content. Empty, corrupt, error-only, or unassessed output is not a successful answer. Any such lane has an error receipt, not a manufactured success. Full roster evaluation with no admitted lanes may be bookkeeping-complete if all skips have reasons, but is always useful-outcome failure.

The optional GREEN label means **complete bookkeeping plus useful-outcome success**, with a parent synthesis that preserves dissent, distinguishes verified from unverified claims, and confirms no silent model/provider substitution occurred. An all-error run is never GREEN. A complete degraded run is not GREEN. If bookkeeping is incomplete, any usable answers remain provisional and must not be presented as a completed council.

A shell burst that launched commands is not a completed council. A model-generated summary that hides failed or dissenting lanes is not a completed council. The regression is a documentation tripwire with test-only logical record fixtures and negative mutations; it does not prove live invocation, scheduling, cancellation, redaction, or inference behavior.
