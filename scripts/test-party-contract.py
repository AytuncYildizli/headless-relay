#!/usr/bin/env python3
"""Documentation tripwire and test-only record fixtures; NOT a council executor.

No provider calls, registry reads, authentication, scheduling or runtime enforcement.
Clauses must be visible, anchored in the relevant Markdown section (not comments).
"""
import copy
import json
from pathlib import Path
import re
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent

# Exact normative clauses: intentionally small reviewable documentation tripwires.
CLAUSES = {
    "payload_isolation": ("Scheduling rules", "- For payload-only tasks, revoke inherited repository/tool access before dispatch: use a fresh per-lane non-repository cwd and a transport that disables file-reading, command execution, MCP/hooks, and equivalent native-subagent tools; an empty cwd alone is not isolation."),
    "payload_block": ("Scheduling rules", "- If that isolation cannot be established for a payload-only lane, mark it `blocked_egress` and do not invoke it; ask for explicitly expanded access only if needed, never infer it from Party Mode or a frozen brief."),
    "native": ("Roster receipt", "- Same-provider lanes MUST be admitted with `transport=native_subagent` when the harness supplies that transport and all gates pass; invoke them with the canonical user brief and require an independent output/error receipt."),
    "native_unavailable": ("Roster receipt", "- If the harness lacks native subagent transport, mark that lane `unavailable` with a reason; do not call its same-provider headless CLI as a fallback."),
    "receipt": ("Completion and useful outcome", "- Bookkeeping is `complete` only if the canonical brief exists, the full roster was evaluated, every skipped lane has a reason, and every admitted lane (including native subagents) has a terminal output/error receipt."),
    "missing_receipt": ("Completion and useful outcome", "- A missing receipt or nonterminal lane makes bookkeeping `incomplete`, never GREEN, even when other lanes answered."),
    "failure": ("Completion and useful outcome", "- With zero usable independent answers, the outcome is `failure`; complete bookkeeping does not imply useful success."),
    "degraded": ("Completion and useful outcome", "- With one usable independent answer, or any failed/unavailable/blocked candidate, the outcome is `degraded`; count native and external lanes equally, and never count the parent synthesis as an independent answer."),
    "success": ("Completion and useful outcome", "- The outcome is `success` only with at least two usable independent answers and no failed/unavailable/blocked candidates; this is participation success, not proof that the claims are true."),
    "timeout": ("Scheduling rules", "- Give each admitted lane, including native subagents, a bounded timeout chosen before dispatch; persist timeout/error receipts and preserve successful sibling artifacts. Never retry indefinitely."),
    "privacy": ("Run directory", "- Never persist credentials, raw auth output, or secret-bearing environment dumps in the manifest or lane receipts; redact secret-bearing stdout/stderr before persistence and apply the user's retention/cleanup policy."),
    "private_dir": ("Run directory", "- Create a fresh private run directory with mode 700 and brief/artifact files with mode 600; these permissions do not isolate processes sharing the same UID."),
    "context": ("Scheduling rules", "- Do not grant repository, network, or parent tool permissions merely because Party Mode was requested; pass only allowed context and retain each transport's least-privilege safety contract."),
    "canonical": ("Canonical user brief", "- Normalize the allowed user task/context once by removing trailing LF bytes, then freeze that canonical UTF-8 user payload for every admitted lane; never shorten or improve it per model."),
    "context_equality": ("Canonical user brief", "- This promises the same canonical user brief, not identical total model context; harness/system/tool instructions differ. Raw command substitution removes trailing newlines, so it does not preserve arbitrary source-file bytes."),
    "transport": ("Canonical user brief", "- Send the canonical file through stdin or a quoted argv adapter, and the same user payload through native subagent transport; wrappers may add transport/safety instructions but must not rewrite the user brief."),
}


def visible(text):
    return re.sub(r"<!--[\s\S]*?-->", "", text)


def sections(text):
    result = {}
    current = None
    for line in visible(text).splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            result[current] = []
        elif current is not None:
            result[current].append(line)
    return result


def violations(ref, skill, readme):
    errors = []
    parts = sections(ref)
    for name, (section, clause) in CLAUSES.items():
        if clause not in parts.get(section, []):
            errors.append(name)
    if not re.search(r"^### Scenario C — Party Mode / Council Mode", visible(skill), re.M):
        errors.append("skill_trigger")
    if not re.search(r"^[^\n]*\[references/party-mode.md\]\(references/party-mode.md\)[^\n]*$", visible(skill), re.M):
        errors.append("skill_link")
    if not re.search(r"^- \*\*Party / Council Mode\*\*:", visible(readme), re.M):
        errors.append("readme_feature")
    if "documentation tripwire" not in visible(readme):
        errors.append("honest_test_scope")
    # Keep existing opt-in, roster, no-auth-churn, sequencing and dissent rules.
    for phrase in ("`ask everyone`", "`her şeyi dene`", "every built-in lane plus every valid custom target", "Never install a binary, log in, rotate auth, or silently substitute another model", "Run Antigravity sequentially", "heavyweight local custom targets sequentially", "Preserve minority dissent", "A majority vote is not evidence"):
        if not re.search(r"^(?:[1-8]\. |[-] |Party Mode ).*" + re.escape(phrase) + r".*$", visible(ref), re.M):
            errors.append(phrase)
    # Validate the illustrative manifest, not any real run or provider identity.
    match = re.search(r"^```json\n(.*?)\n```$", "\n".join(parts.get("Roster receipt", [])), re.M | re.S)
    try:
        manifest = json.loads(match.group(1)) if match else {}
        if not isinstance(manifest, dict) or not isinstance(manifest.get("lanes"), list):
            raise ValueError("manifest must contain a lane list")
        lanes = manifest["lanes"]
        for lane in lanes:
            if not isinstance(lane, dict) or not set(("lane", "provider", "model", "transport", "state", "terminal", "artifact", "reason")) <= lane.keys():
                raise ValueError("missing lane fields")
            if lane["state"] not in {"admitted", "unavailable", "blocked_policy", "blocked_egress"}:
                raise ValueError("invalid admission state")
            if lane["terminal"] not in {"output", "error", "timeout", "not_invoked"}:
                raise ValueError("invalid terminal state")
        if not any(l["state"] == "admitted" and l["transport"] == "native_subagent" for l in lanes):
            raise ValueError("missing native example")
    except (KeyError, AssertionError, ValueError, TypeError):
        errors.append("manifest")
    return errors


def fixture_outcome(lanes, brief=True):
    """TEST ONLY: logical examples of documented rules, NOT product runtime.

    'usable' is a fixture assertion, not a stdout/parser correctness guarantee.
    """
    complete = brief and bool(lanes)
    usable = 0
    impaired = False
    for lane in lanes:
        if lane["state"] != "admitted":
            complete = complete and bool(lane.get("reason"))
            impaired = True
            continue
        terminal = lane.get("terminal")
        receipt = bool(lane.get("artifact"))
        complete = complete and terminal in {"output", "error", "timeout"} and receipt
        good = terminal == "output" and receipt and lane.get("usable", False)
        usable += int(good)
        impaired = impaired or not good
    outcome = "failure" if usable == 0 else "degraded" if usable == 1 or impaired else "success"
    return {"bookkeeping": "complete" if complete else "incomplete", "outcome": outcome}


class DocumentationContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ref = (ROOT / "references/party-mode.md").read_text(encoding="utf-8")
        cls.skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        cls.readme = (ROOT / "README.md").read_text(encoding="utf-8")

    def test_current_documentation(self):
        self.assertEqual(violations(self.ref, self.skill, self.readme), [])

    def test_negative_clause_mutations(self):
        for name, (_, clause) in CLAUSES.items():
            with self.subTest(clause=name):
                self.assertIn(clause, self.ref, "positive clause must exist before mutation")
                changed = self.ref.replace(clause, "<!-- " + clause + " -->")
                self.assertIn(name, violations(changed, self.skill, self.readme))

    def test_comments_only_protocol_fails(self):
        self.assertIn("native", violations("<!--\n" + self.ref + "\n-->", self.skill, self.readme))
        self.assertIn("skill_trigger", violations(self.ref, "<!--\n" + self.skill + "\n-->", self.readme))
        self.assertIn("readme_feature", violations(self.ref, self.skill, "<!--\n" + self.readme + "\n-->"))

    def test_documented_canonical_payload_stdin_and_argv(self):
        # Exercise only the published payload preparation, never any model CLI.
        match = re.search(r"<<'PY'\n(.*?)\nPY", self.ref, re.S)
        if match is None:
            self.fail("documented normalization example required")
        with tempfile.TemporaryDirectory(prefix="party-contract-", dir=os.environ.get("TMPDIR")) as tmp:
            source, target = Path(tmp) / "source.md", Path(tmp) / "brief.md"
            for payload in (b"question\n\n", "allowed context: ş\n".encode(), b"quoted $HOME `no-exec`\n"):
                source.write_bytes(payload)
                result = subprocess.run([sys.executable, "-c", match.group(1), str(source), str(target)], capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                expected = payload.rstrip(b"\n")
                with target.open("rb") as brief:
                    stdin = subprocess.run([sys.executable, "-c", "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())"], stdin=brief, capture_output=True, check=True).stdout
                argv = subprocess.run(["/bin/sh", "-c", 'printf %s "$(cat "$1")"', "fixture", str(target)], capture_output=True, check=True).stdout
                self.assertEqual(stdin, expected)
                self.assertEqual(argv, expected)
            for payload in (b"\n\n", b"task\0context", b"\xff"):
                source.write_bytes(payload)
                result = subprocess.run([sys.executable, "-c", match.group(1), str(source), str(target)], capture_output=True)
                self.assertNotEqual(result.returncode, 0)

    def test_manifest_missing_native_or_terminal_rejected(self):
        for old, new in (("native_subagent", "headless_cli"), ('"terminal":', '"not_terminal":')):
            with self.subTest(field=old):
                self.assertIn(old, self.ref)
                self.assertIn("manifest", violations(self.ref.replace(old, new), self.skill, self.readme))


class TestOnlyRecordRules(unittest.TestCase):
    def lane(self, name, transport="headless_cli", **changes):
        lane = dict(lane=name, provider=name, model="fixture-model", transport=transport,
                    state="admitted", terminal="output", artifact=name + ".md", usable=True)
        lane.update(changes)
        return lane

    def test_native_requires_independent_receipt(self):
        lanes = [self.lane("gpt", "native_subagent", artifact=None), self.lane("glm")]
        self.assertEqual(fixture_outcome(lanes), dict(bookkeeping="incomplete", outcome="degraded"))

    def test_native_and_external_count_equally(self):
        lanes = [self.lane("gpt", "native_subagent"), self.lane("glm")]
        self.assertEqual(fixture_outcome(lanes), dict(bookkeeping="complete", outcome="success"))

    def test_all_errors_complete_but_failure(self):
        lanes = [self.lane("gpt", "native_subagent", terminal="error", usable=False), self.lane("glm", terminal="timeout", usable=False)]
        self.assertEqual(fixture_outcome(lanes), dict(bookkeeping="complete", outcome="failure"))

    def test_timeout_preserves_successful_sibling(self):
        lanes = [self.lane("glm"), self.lane("gpt", "native_subagent", terminal="timeout", usable=False)]
        original = copy.deepcopy(lanes)
        self.assertEqual(fixture_outcome(lanes), dict(bookkeeping="complete", outcome="degraded"))
        self.assertEqual(lanes, original)

    def test_unavailable_native_needs_reason(self):
        for reason, expected in (("harness has no native transport", "complete"), ("", "incomplete")):
            with self.subTest(reason=reason):
                lanes = [self.lane("gpt", "none", state="unavailable", terminal="not_invoked", reason=reason), self.lane("glm")]
                self.assertEqual(fixture_outcome(lanes), dict(bookkeeping=expected, outcome="degraded"))

    def test_zero_one_empty_nonterminal_and_missing_brief(self):
        self.assertEqual(fixture_outcome([]), dict(bookkeeping="incomplete", outcome="failure"))
        self.assertEqual(fixture_outcome([self.lane("glm")])["outcome"], "degraded")
        self.assertEqual(fixture_outcome([self.lane("glm", usable=False)])["outcome"], "failure")
        self.assertEqual(fixture_outcome([self.lane("glm", terminal="running")])["bookkeeping"], "incomplete")
        self.assertEqual(fixture_outcome([self.lane("glm")], brief=False)["bookkeeping"], "incomplete")


if __name__ == "__main__":
    unittest.main(verbosity=2)
