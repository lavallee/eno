#!/usr/bin/env python3
"""Run disposable, receipt-bearing Eno skill trials through Codex and Claude."""

from __future__ import annotations

import argparse
import concurrent.futures
import difflib
import functools
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import textwrap
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PILOT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PILOT_ROOT.parents[1]
SPINDLE_ROOT = REPO_ROOT.parent / "spindle"
CANDIDATE_SKILL = PILOT_ROOT / "skills" / "candidate" / "eno-vault-pilot"
CLAUDE_CANDIDATE_SKILL = PILOT_ROOT / "skills" / "claude-candidate" / "eno-vault"
INCUMBENT_SKILL = PILOT_ROOT / "skills" / "incumbent" / "eno-vault-pilot"
PRODUCTION_SKILL = REPO_ROOT / "packages" / "eno-mcp" / "skills" / "eno-vault"
DEMO_VAULT = REPO_ROOT / "examples" / "demo-vault"
STATE_ROOT = PILOT_ROOT / ".state"
RUNS_ROOT = PILOT_ROOT / "runs"

MODELS = {
    "gpt-5.6-sol": {"effort": "high", "role": "reviewer"},
    "gpt-5.6-terra": {"effort": "medium", "role": "explorer"},
}
CLAUDE_MODELS = {
    "claude-sonnet-5": {
        "effort": "medium",
        "role": "explorer",
        "budget_usd": 0.75,
        "profile_id": "claude-sonnet-explorer-2026-07",
    },
    "claude-opus-5": {
        "effort": "high",
        "role": "reviewer",
        "budget_usd": 1.50,
        "profile_id": "claude-opus-reviewer-2026-07",
    },
}
ARMS = ("none", "incumbent", "core", "profiled", "production")
ENO_TOOLSET_FILES = (
    REPO_ROOT / "packages" / "eno-mcp" / "src" / "eno_mcp" / "server.py",
    REPO_ROOT / "packages" / "eno-mcp" / "src" / "eno_mcp" / "tools.py",
)


@dataclass(frozen=True)
class Trial:
    case_id: str
    arm: str
    model: str
    invocation: str = "forced"
    repeat: int = 1


def _read_cases() -> dict[str, dict[str, Any]]:
    rows = json.loads((PILOT_ROOT / "cases.json").read_text(encoding="utf-8"))
    return {row["id"]: row for row in rows}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _file_set_digest(paths: tuple[Path, ...], *, root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return "sha256:" + digest.hexdigest()


@functools.cache
def _codex_build() -> str:
    result = _run(["codex", "--version"], cwd=REPO_ROOT)
    if result.returncode != 0:
        raise RuntimeError(f"cannot identify Codex build: {result.stderr or result.stdout}")
    return result.stdout.strip().removeprefix("codex-cli ")


@functools.cache
def _claude_build() -> str:
    result = _run(["claude", "--version"], cwd=REPO_ROOT)
    if result.returncode != 0:
        raise RuntimeError(f"cannot identify Claude build: {result.stderr or result.stdout}")
    return result.stdout.strip().split()[0]


def _canonical_claude_model(value: Any) -> str | None:
    """Strip Claude's bracketed runtime variant from an Agent result model."""

    if not isinstance(value, str) or not value:
        return None
    return re.sub(r"\[[^]]+\]$", "", value)


def _eno_toolset_digest() -> str:
    return _file_set_digest(
        ENO_TOOLSET_FILES,
        root=REPO_ROOT / "packages" / "eno-mcp" / "src" / "eno_mcp",
    )


def _markdown_snapshot(vault: Path) -> dict[str, str]:
    return {
        path.relative_to(vault).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted(vault.rglob("*.md"))
    }


def _run(
    command: list[str], *, cwd: Path, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        timeout=420,
        check=False,
    )


def _realize(
    trial: Trial, run_id: str, *, skill_dir: Path = CANDIDATE_SKILL
) -> tuple[Path, dict[str, Any]]:
    profile = MODELS[trial.model]
    matched_arm = trial.arm in {"profiled", "production"}
    role = profile["role"] if matched_arm else "core-control"
    command = [
        "uv",
        "run",
        "--directory",
        str(SPINDLE_ROOT),
        "spindle",
        "realize",
        str(skill_dir),
        "--session-id",
        run_id,
        "--harness",
        "codex",
        "--model",
        trial.model,
        "--effort",
        profile["effort"],
        "--role",
        role,
        "--harness-build",
        _codex_build(),
        "--toolset-digest",
        _eno_toolset_digest(),
        "--json",
    ]
    if matched_arm:
        command.append("--strict")
    env = os.environ.copy()
    env["SPINDLE_HOME"] = str(STATE_ROOT)
    result = _run(command, cwd=REPO_ROOT, env=env)
    if result.returncode != 0:
        raise RuntimeError(
            f"spindle realize failed ({result.returncode}): {result.stderr or result.stdout}"
        )
    receipt = json.loads(result.stdout)
    return Path(receipt["path"]), receipt


def _realize_claude(trial: Trial, run_id: str) -> tuple[Path, dict[str, Any]]:
    profile = CLAUDE_MODELS[trial.model]
    matched_arm = trial.arm in {"profiled", "production"}
    role = profile["role"] if matched_arm else "core-control"
    skill_dir = CLAUDE_CANDIDATE_SKILL if trial.arm == "profiled" else PRODUCTION_SKILL
    command = [
        "uv",
        "run",
        "--directory",
        str(SPINDLE_ROOT),
        "spindle",
        "realize",
        str(skill_dir),
        "--session-id",
        run_id,
        "--harness",
        "claude",
        "--requested-model",
        trial.model,
        "--served-model",
        trial.model,
        "--effort",
        profile["effort"],
        "--role",
        role,
        "--harness-build",
        _claude_build(),
        "--toolset-digest",
        _eno_toolset_digest(),
        "--json",
    ]
    if matched_arm:
        command.append("--strict")
    env = os.environ.copy()
    env["SPINDLE_HOME"] = str(STATE_ROOT)
    result = _run(command, cwd=REPO_ROOT, env=env)
    if result.returncode != 0:
        raise RuntimeError(
            f"spindle realize failed ({result.returncode}): {result.stderr or result.stdout}"
        )
    receipt = json.loads(result.stdout)
    return Path(receipt["path"]), receipt


def _tool_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    calls = []
    for event in events:
        item = event.get("item", {})
        if event.get("type") == "item.completed" and item.get("type") == "mcp_tool_call":
            calls.append(
                {
                    "server": item.get("server"),
                    "tool": item.get("tool"),
                    "arguments": item.get("arguments") or {},
                    "status": item.get("status"),
                    "error": item.get("error"),
                }
            )
    return calls


def _claude_tool_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results: dict[str, bool] = {}
    for event in events:
        if event.get("type") != "user":
            continue
        for block in event.get("message", {}).get("content", []):
            if block.get("type") == "tool_result":
                results[block.get("tool_use_id", "")] = not bool(block.get("is_error"))

    calls: list[dict[str, Any]] = []
    for event in events:
        if event.get("type") != "assistant":
            continue
        parent_tool_use_id = event.get("parent_tool_use_id")
        event_model = event.get("message", {}).get("model")
        for block in event.get("message", {}).get("content", []):
            if block.get("type") != "tool_use":
                continue
            raw_name = block.get("name", "")
            if not raw_name.startswith("mcp__eno__"):
                continue
            tool_use_id = block.get("id", "")
            calls.append(
                {
                    "server": "eno",
                    "tool": raw_name.removeprefix("mcp__eno__"),
                    "arguments": block.get("input") or {},
                    "status": "completed" if results.get(tool_use_id, True) else "failed",
                    "error": None if results.get(tool_use_id, True) else "tool-result-error",
                    "parent_tool_use_id": parent_tool_use_id,
                    "model": event_model,
                }
            )
    return calls


def _usage(events: list[dict[str, Any]]) -> dict[str, int]:
    for event in reversed(events):
        if event.get("type") == "turn.completed":
            return event.get("usage") or {}
    return {}


def _thread_id(events: list[dict[str, Any]]) -> str | None:
    for event in events:
        if event.get("type") == "thread.started":
            return event.get("thread_id")
    return None


def _realized_instructions(skill_path: Path) -> str:
    """Return the realized skill body for projection into a child agent layer."""

    text = (skill_path / "SKILL.md").read_text(encoding="utf-8")
    if text.startswith("---\n"):
        _, separator, body = text[4:].partition("\n---\n")
        if separator:
            return body.strip()
    return text.strip()


def _find_child_evidence(
    *, parent_thread_id: str, agent_role: str, started_at: float
) -> dict[str, Any] | None:
    """Inspect Codex's local rollout receipt for a spawned custom agent.

    Successful subagent spawns are not always represented in the parent's JSON
    event stream. The child rollout's session metadata is the authoritative
    receipt for parentage, configured role, served model, and effort.
    """

    sessions_root = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "sessions"
    if not sessions_root.exists():
        return None

    candidates = sorted(
        (
            path
            for path in sessions_root.rglob("rollout-*.jsonl")
            if path.stat().st_mtime >= started_at - 5
        ),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for path in candidates:
        records: list[dict[str, Any]] = []
        try:
            records = [
                json.loads(line)
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip().startswith("{")
            ]
        except (OSError, json.JSONDecodeError):
            continue
        if not records or records[0].get("type") != "session_meta":
            continue
        session = records[0].get("payload", {})
        if session.get("parent_thread_id") != parent_thread_id:
            continue
        if session.get("agent_role") != agent_role:
            continue

        context = next(
            (
                record.get("payload", {})
                for record in records
                if record.get("type") == "turn_context"
            ),
            {},
        )
        developer_text = "\n".join(
            content.get("text", "")
            for record in records
            if record.get("type") == "response_item"
            and record.get("payload", {}).get("type") == "message"
            and record.get("payload", {}).get("role") == "developer"
            for content in record.get("payload", {}).get("content", [])
            if content.get("type") == "input_text"
        )
        tools = [
            record.get("payload", {}).get("invocation", {}).get("tool")
            for record in records
            if record.get("type") == "event_msg"
            and record.get("payload", {}).get("type") == "mcp_tool_call_end"
            and record.get("payload", {}).get("invocation", {}).get("server") == "eno"
        ]
        realization_markers = sorted(
            set(re.findall(r"spindle-(?:profile|realization):[a-z0-9:-]+", developer_text))
        )
        return {
            "rollout_path": str(path),
            "thread_id": session.get("id"),
            "parent_thread_id": session.get("parent_thread_id"),
            "agent_role": session.get("agent_role"),
            "model": context.get("model"),
            "effort": context.get("effort"),
            "developer_instruction_sha256": hashlib.sha256(
                developer_text.encode("utf-8")
            ).hexdigest(),
            "realization_markers": realization_markers,
            "eno_tools": [tool for tool in tools if tool],
        }
    return None


def _score(
    case: dict[str, Any],
    final_text: str,
    calls: list[dict[str, Any]],
    changed_paths: list[str],
) -> dict[str, Any]:
    tools = [call["tool"] for call in calls if call["status"] == "completed"]
    checks: list[dict[str, Any]] = []

    for tool in case.get("required_tools", []):
        checks.append({"check": f"used:{tool}", "pass": tool in tools})
    for group in case.get("required_tool_groups", []):
        checks.append(
            {
                "check": f"used-any:{'|'.join(group)}",
                "pass": any(tool in tools for tool in group),
            }
        )
    for group in case.get("required_term_groups", []):
        checks.append(
            {
                "check": f"mentioned-any:{'|'.join(group)}",
                "pass": any(term.casefold() in final_text.casefold() for term in group),
            }
        )
    for tool in case.get("forbidden_tools", []):
        checks.append({"check": f"avoided:{tool}", "pass": tool not in tools})
    for prefix in case.get("forbidden_tool_prefixes", []):
        checks.append(
            {
                "check": f"avoided-prefix:{prefix}",
                "pass": not any(tool.startswith(prefix) for tool in tools),
            }
        )

    expected_path = case.get("expected_write_path")
    if expected_path:
        append_calls = [call for call in calls if call["tool"] == "eno_append_to_note"]
        checks.append(
            {
                "check": f"write-target:{expected_path}",
                "pass": any(
                    call["arguments"].get("path") == expected_path for call in append_calls
                ),
            }
        )

    expected_changes = sorted(case.get("expected_changed_paths", []))
    checks.append(
        {
            "check": "vault-change-set",
            "pass": sorted(changed_paths) == expected_changes,
            "observed": sorted(changed_paths),
            "expected": expected_changes,
        }
    )
    passed = sum(bool(check["pass"]) for check in checks)
    return {
        "passed": passed,
        "total": len(checks),
        "fraction": round(passed / len(checks), 4) if checks else 1.0,
        "checks": checks,
    }


def _trial_dir(batch_dir: Path, trial: Trial) -> Path:
    suffix = uuid.uuid4().hex[:8]
    name = (
        f"{trial.case_id}__{trial.arm}__{trial.model}__"
        f"{trial.invocation}__r{trial.repeat}__{suffix}"
    )
    path = batch_dir / name
    path.mkdir(parents=True)
    return path


def run_trial(batch_dir: Path, cases: dict[str, dict[str, Any]], trial: Trial) -> dict[str, Any]:
    started = time.monotonic()
    case = cases[trial.case_id]
    profile = MODELS[trial.model]
    run_dir = _trial_dir(batch_dir, trial)
    run_id = run_dir.name

    skill_path: Path | None = None
    realization: dict[str, Any] | None = None
    if trial.arm == "incumbent":
        skill_path = INCUMBENT_SKILL
    elif trial.arm in {"core", "profiled"}:
        skill_path, realization = _realize(trial, run_id)
    elif trial.arm == "production":
        skill_path, realization = _realize(trial, run_id, skill_dir=PRODUCTION_SKILL)

    with (
        tempfile.TemporaryDirectory(prefix="eno-pilot-work-") as work_raw,
        tempfile.TemporaryDirectory(prefix="eno-pilot-vault-") as vault_raw,
    ):
        work = Path(work_raw)
        vault = Path(vault_raw)
        shutil.copytree(
            DEMO_VAULT, vault, dirs_exist_ok=True, ignore=shutil.ignore_patterns(".eno")
        )
        index_result = _run(["uv", "run", "eno", "--vault", str(vault), "index"], cwd=REPO_ROOT)
        if index_result.returncode != 0:
            raise RuntimeError(f"eno index failed: {index_result.stderr or index_result.stdout}")
        before = _markdown_snapshot(vault)

        prompt = case["prompt"]
        session_skill_path: Path | None = None
        skill_discovered: bool | None = None
        if skill_path is not None:
            skill_name = skill_path.name
            session_skill_path = work / ".codex" / "skills" / skill_name
            session_skill_path.parent.mkdir(parents=True)
            session_skill_path.symlink_to(skill_path, target_is_directory=True)
            if trial.invocation == "forced":
                prompt = f"Use ${skill_name} for this task.\n\n{prompt}"
            discovery = _run(["codex", "debug", "prompt-input", f"Use ${skill_name}."], cwd=work)
            discovered_at = str(session_skill_path / "SKILL.md")
            discovered_target = str(skill_path / "SKILL.md")
            skill_discovered = (
                discovery.returncode == 0
                and skill_name in discovery.stdout
                and (discovered_at in discovery.stdout or discovered_target in discovery.stdout)
            )
            (run_dir / "skill-discovery.json").write_text(
                json.dumps(
                    {
                        "returncode": discovery.returncode,
                        "expected_session_path": discovered_at,
                        "expected_target_path": discovered_target,
                        "skill_discovered": skill_discovered,
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            if not skill_discovered:
                raise RuntimeError("Codex did not discover the session-local realized skill path")

        final_path = run_dir / "final.txt"
        command = [
            "codex",
            "exec",
            "--ignore-user-config",
            "--strict-config",
            "--ephemeral",
            "--skip-git-repo-check",
            "--json",
            "-C",
            str(work),
            "-s",
            "read-only",
            "-m",
            trial.model,
            "-c",
            f'model_reasoning_effort="{profile["effort"]}"',
            "-c",
            'approval_policy="never"',
            "-c",
            'mcp_servers.eno.command="uv"',
            "-c",
            f'mcp_servers.eno.args=["run","--directory",{json.dumps(str(REPO_ROOT))},"eno-mcp"]',
            "-c",
            (
                "mcp_servers.eno.env="
                f'{{ENO_VAULT_DIR={json.dumps(str(vault))},ENO_AGENT_NAME="EnoPilot"}}'
            ),
            "-c",
            'mcp_servers.eno.default_tools_approval_mode="approve"',
            "-o",
            str(final_path),
        ]
        command.append(prompt)

        codex_result = _run(command, cwd=REPO_ROOT)
        (run_dir / "stderr.txt").write_text(codex_result.stderr, encoding="utf-8")
        (run_dir / "events.jsonl").write_text(codex_result.stdout, encoding="utf-8")
        events = [
            json.loads(line)
            for line in codex_result.stdout.splitlines()
            if line.strip().startswith("{")
        ]
        final_text = final_path.read_text(encoding="utf-8") if final_path.exists() else ""

        after = _markdown_snapshot(vault)
        changed_paths = sorted(
            path for path in set(before) | set(after) if before.get(path) != after.get(path)
        )
        diff_lines: list[str] = []
        for path in changed_paths:
            diff_lines.extend(
                difflib.unified_diff(
                    before.get(path, "").splitlines(keepends=True),
                    after.get(path, "").splitlines(keepends=True),
                    fromfile=f"before/{path}",
                    tofile=f"after/{path}",
                )
            )
        (run_dir / "vault.diff").write_text("".join(diff_lines), encoding="utf-8")

    calls = _tool_events(events)
    observed_artifact = final_text + "\n" + "".join(diff_lines)
    score = _score(case, observed_artifact, calls, changed_paths)
    metadata = {
        "schema_version": 1,
        "run_id": run_id,
        "created_at": datetime.now(UTC).isoformat(),
        "case_id": trial.case_id,
        "case_suite": case.get("suite", "baseline"),
        "prompt_sha256": hashlib.sha256(case["prompt"].encode("utf-8")).hexdigest(),
        "arm": trial.arm,
        "invocation": "none" if trial.arm == "none" else trial.invocation,
        "repeat": trial.repeat,
        "model": trial.model,
        "effort": profile["effort"],
        "role": profile["role"],
        "harness_build": _codex_build(),
        "toolset_digest": _eno_toolset_digest(),
        "skill_path": str(skill_path) if skill_path else None,
        "session_skill_path": str(session_skill_path) if session_skill_path else None,
        "skill_discovered": skill_discovered,
        "skill_sha256": _sha256(skill_path / "SKILL.md") if skill_path else None,
        "realization": realization,
        "codex_returncode": codex_result.returncode,
        "duration_seconds": round(time.monotonic() - started, 3),
        "usage": _usage(events),
        "tool_calls": calls,
        "changed_paths": changed_paths,
        "score": score,
    }
    (run_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return metadata


def run_claude_trial(
    batch_dir: Path, cases: dict[str, dict[str, Any]], trial: Trial
) -> dict[str, Any]:
    """Run one isolated Claude print-mode trial with an Eno MCP receipt."""

    started = time.monotonic()
    case = cases[trial.case_id]
    profile = CLAUDE_MODELS[trial.model]
    run_dir = _trial_dir(batch_dir, trial)
    run_id = "claude__" + run_dir.name

    skill_path: Path | None = None
    realization: dict[str, Any] | None = None
    if trial.arm == "incumbent":
        skill_path = INCUMBENT_SKILL
    elif trial.arm in {"core", "profiled", "production"}:
        skill_path, realization = _realize_claude(trial, run_id)

    with (
        tempfile.TemporaryDirectory(prefix="eno-pilot-claude-work-") as work_raw,
        tempfile.TemporaryDirectory(prefix="eno-pilot-claude-vault-") as vault_raw,
    ):
        work = Path(work_raw)
        vault = Path(vault_raw)
        shutil.copytree(
            DEMO_VAULT, vault, dirs_exist_ok=True, ignore=shutil.ignore_patterns(".eno")
        )
        index_result = _run(["uv", "run", "eno", "--vault", str(vault), "index"], cwd=REPO_ROOT)
        if index_result.returncode != 0:
            raise RuntimeError(f"eno index failed: {index_result.stderr or index_result.stdout}")
        before = _markdown_snapshot(vault)

        prompt = case["prompt"]
        skill_name: str | None = None
        session_skill_path: Path | None = None
        if skill_path is not None:
            skill_name = skill_path.name
            session_skill_path = work / ".claude" / "skills" / skill_name
            session_skill_path.parent.mkdir(parents=True)
            session_skill_path.symlink_to(skill_path, target_is_directory=True)
            if trial.invocation == "forced":
                prompt = f"/{skill_name}\n\n{prompt}"

        mcp_config = work / "mcp.json"
        mcp_config.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "eno": {
                            "command": "uv",
                            "args": ["run", "--directory", str(REPO_ROOT), "eno-mcp"],
                            "env": {
                                "ENO_VAULT_DIR": str(vault),
                                "ENO_AGENT_NAME": "EnoPilotClaude",
                            },
                        }
                    }
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        command = [
            "claude",
            "-p",
            "--setting-sources",
            "project",
            "--model",
            trial.model,
            "--effort",
            profile["effort"],
            "--output-format",
            "stream-json",
            "--verbose",
            "--no-session-persistence",
            "--strict-mcp-config",
            "--mcp-config",
            str(mcp_config),
            "--allowedTools",
            "mcp__eno__*",
            "--permission-mode",
            "dontAsk",
            "--max-budget-usd",
            str(profile["budget_usd"]),
            prompt,
        ]
        claude_result = _run(command, cwd=work)
        (run_dir / "stderr.txt").write_text(claude_result.stderr, encoding="utf-8")
        (run_dir / "events.jsonl").write_text(claude_result.stdout, encoding="utf-8")
        events = [
            json.loads(line)
            for line in claude_result.stdout.splitlines()
            if line.strip().startswith("{")
        ]
        init = next(
            (
                event
                for event in events
                if event.get("type") == "system" and event.get("subtype") == "init"
            ),
            {},
        )
        result_event = next(
            (event for event in reversed(events) if event.get("type") == "result"),
            {},
        )
        final_text = result_event.get("result") or ""
        (run_dir / "final.txt").write_text(final_text, encoding="utf-8")

        after = _markdown_snapshot(vault)
        changed_paths = sorted(
            path for path in set(before) | set(after) if before.get(path) != after.get(path)
        )
        diff_lines: list[str] = []
        for path in changed_paths:
            diff_lines.extend(
                difflib.unified_diff(
                    before.get(path, "").splitlines(keepends=True),
                    after.get(path, "").splitlines(keepends=True),
                    fromfile=f"before/{path}",
                    tofile=f"after/{path}",
                )
            )
        (run_dir / "vault.diff").write_text("".join(diff_lines), encoding="utf-8")

    calls = _claude_tool_events(events)
    observed_artifact = final_text + "\n" + "".join(diff_lines)
    score = _score(case, observed_artifact, calls, changed_paths)
    discovered_skills = init.get("skills") or []
    skill_discovered = skill_name in discovered_skills if skill_name else None
    metadata = {
        "schema_version": 1,
        "run_id": run_id,
        "created_at": datetime.now(UTC).isoformat(),
        "harness": "claude",
        "case_id": trial.case_id,
        "case_suite": case.get("suite", "baseline"),
        "prompt_sha256": hashlib.sha256(case["prompt"].encode("utf-8")).hexdigest(),
        "arm": trial.arm,
        "invocation": "none" if trial.arm == "none" else trial.invocation,
        "repeat": trial.repeat,
        "requested_model": trial.model,
        "served_model": init.get("model"),
        "effort": profile["effort"],
        "role": profile["role"],
        "harness_build": init.get("claude_code_version"),
        "toolset_digest": _eno_toolset_digest(),
        "skill_path": str(skill_path) if skill_path else None,
        "session_skill_path": str(session_skill_path) if session_skill_path else None,
        "skill_discovered": skill_discovered,
        "skill_sha256": _sha256(skill_path / "SKILL.md") if skill_path else None,
        "realization": realization,
        "claude_returncode": claude_result.returncode,
        "is_error": result_event.get("is_error"),
        "terminal_reason": result_event.get("terminal_reason"),
        "permission_denials": result_event.get("permission_denials") or [],
        "duration_seconds": round(time.monotonic() - started, 3),
        "total_cost_usd": result_event.get("total_cost_usd"),
        "usage": result_event.get("usage") or {},
        "model_usage": result_event.get("modelUsage") or {},
        "tool_calls": calls,
        "changed_paths": changed_paths,
        "score": score,
    }
    (run_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if skill_path is not None and not skill_discovered:
        raise RuntimeError("Claude did not discover the session-local skill")
    if init.get("model") != trial.model:
        raise RuntimeError(f"Claude served {init.get('model')!r}, expected {trial.model!r}")
    return metadata


def _claude_agent_dispatches(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return root Agent calls joined to Claude's authoritative result metadata."""

    results: dict[str, dict[str, Any]] = {}
    for event in events:
        if event.get("type") != "user" or event.get("parent_tool_use_id") is not None:
            continue
        tool_result = event.get("tool_use_result")
        if not isinstance(tool_result, dict):
            continue
        for block in event.get("message", {}).get("content", []):
            if block.get("type") == "tool_result":
                results[block.get("tool_use_id", "")] = tool_result

    dispatches: list[dict[str, Any]] = []
    for event in events:
        if event.get("type") != "assistant" or event.get("parent_tool_use_id") is not None:
            continue
        for block in event.get("message", {}).get("content", []):
            if block.get("type") != "tool_use" or block.get("name") != "Agent":
                continue
            tool_use_id = block.get("id", "")
            result = results.get(tool_use_id, {})
            resolved_model_raw = result.get("resolvedModel")
            dispatches.append(
                {
                    "tool_use_id": tool_use_id,
                    "input": block.get("input") or {},
                    "resolved_model": _canonical_claude_model(resolved_model_raw),
                    "resolved_model_raw": resolved_model_raw,
                    "agent_id": result.get("agentId"),
                    "agent_type": result.get("agentType"),
                    "status": result.get("status"),
                    "total_tokens": result.get("totalTokens"),
                    "duration_ms": result.get("totalDurationMs"),
                }
            )
    return dispatches


def run_claude_mixed(
    batch_dir: Path,
    cases: dict[str, dict[str, Any]],
    *,
    parent_model: str,
    child_model: str,
    repeat: int = 1,
) -> dict[str, Any]:
    """Run one Claude parent with a differently modeled, independently realized child."""

    started = time.monotonic()
    case = cases["link-semantics"]
    parent_profile = CLAUDE_MODELS[parent_model]
    child_profile = CLAUDE_MODELS[child_model]
    direction = f"{parent_model}__to__{child_model}"
    run_id = f"claude-mixed__{direction}__r{repeat}__{uuid.uuid4().hex[:8]}"
    run_dir = batch_dir / run_id
    run_dir.mkdir(parents=True)

    parent_path, parent_receipt = _realize_claude(
        Trial("link-semantics", "production", parent_model), run_id + "__parent"
    )
    child_path, child_receipt = _realize_claude(
        Trial("link-semantics", "production", child_model), run_id + "__child"
    )
    child_agent_name = f"eno-{child_profile['role']}-{child_model.removeprefix('claude-')}"
    parent_agent_name = f"eno-router-{parent_model.removeprefix('claude-')}"
    child_route_marker = (
        f"spindle-child-route:{child_receipt['profile_id']}:"
        f"{child_receipt['realization_digest'][:20]}"
    )
    child_prompt = textwrap.dedent(
        f"""
        You are the Eno {child_profile["role"]} child for a delegated vault task.
        Follow this independently realized runtime instruction body:

        <eno-runtime-instructions>
        {_realized_instructions(child_path)}
        </eno-runtime-instructions>

        Complete the delegated request with the available Eno MCP tools. Do not
        delegate again. End your answer with this exact routing receipt on its
        own line: {child_route_marker}
        """
    ).strip()
    parent_prompt = textwrap.dedent(
        f"""
        You are a routing parent. Delegate every user request exactly once to
        the `{child_agent_name}` agent. Do not solve the vault task yourself and
        do not delegate to any other agent. Return the child's substantive
        answer without adding your own vault claims.
        """
    ).strip()

    with (
        tempfile.TemporaryDirectory(prefix="eno-pilot-claude-mixed-work-") as work_raw,
        tempfile.TemporaryDirectory(prefix="eno-pilot-claude-mixed-vault-") as vault_raw,
    ):
        work = Path(work_raw)
        vault = Path(vault_raw)
        shutil.copytree(
            DEMO_VAULT, vault, dirs_exist_ok=True, ignore=shutil.ignore_patterns(".eno")
        )
        index_result = _run(["uv", "run", "eno", "--vault", str(vault), "index"], cwd=REPO_ROOT)
        if index_result.returncode != 0:
            raise RuntimeError(f"eno index failed: {index_result.stderr or index_result.stdout}")
        before = _markdown_snapshot(vault)

        session_skill_path = work / ".claude" / "skills" / "eno-vault"
        session_skill_path.parent.mkdir(parents=True)
        session_skill_path.symlink_to(parent_path, target_is_directory=True)
        eno_server = {
            "type": "stdio",
            "command": "uv",
            "args": ["run", "--directory", str(REPO_ROOT), "eno-mcp"],
            "env": {
                "ENO_VAULT_DIR": str(vault),
                "ENO_AGENT_NAME": "EnoPilotClaudeChild",
            },
        }
        agents = {
            parent_agent_name: {
                "description": "Routes the supplied vault task to the named Eno child exactly once.",
                "prompt": parent_prompt,
                "tools": ["Agent"],
                "model": parent_model,
                "effort": parent_profile["effort"],
                "permissionMode": "dontAsk",
                "skills": ["eno-vault"],
                "maxTurns": 6,
                "background": False,
            },
            child_agent_name: {
                "description": "Handles the delegated Eno vault task with its session realization.",
                "prompt": child_prompt,
                "tools": [
                    "mcp__eno__eno_search",
                    "mcp__eno__eno_note",
                    "mcp__eno__eno_neighbors",
                    "mcp__eno__eno_concepts",
                    "mcp__eno__eno_drift",
                ],
                "model": child_model,
                "effort": child_profile["effort"],
                "permissionMode": "dontAsk",
                "mcpServers": [{"eno": eno_server}],
                "maxTurns": 24,
                "background": False,
            },
        }
        (run_dir / "agents.json").write_text(
            json.dumps(agents, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        command = [
            "claude",
            "-p",
            "--setting-sources",
            "project",
            "--agents",
            json.dumps(agents, separators=(",", ":")),
            "--agent",
            parent_agent_name,
            "--model",
            parent_model,
            "--effort",
            parent_profile["effort"],
            "--output-format",
            "stream-json",
            "--verbose",
            "--forward-subagent-text",
            "--no-session-persistence",
            "--strict-mcp-config",
            "--permission-mode",
            "dontAsk",
            "--allowedTools",
            "Agent,mcp__eno__*",
            "--max-budget-usd",
            "2.25",
            case["prompt"],
        ]
        claude_env = os.environ.copy()
        claude_env.pop("CLAUDE_CODE_SUBAGENT_MODEL", None)
        claude_env["CLAUDE_AGENT_SDK_DISABLE_BUILTIN_AGENTS"] = "1"
        claude_result = _run(command, cwd=work, env=claude_env)
        (run_dir / "stderr.txt").write_text(claude_result.stderr, encoding="utf-8")
        (run_dir / "events.jsonl").write_text(claude_result.stdout, encoding="utf-8")
        events = [
            json.loads(line)
            for line in claude_result.stdout.splitlines()
            if line.strip().startswith("{")
        ]
        init = next(
            (
                event
                for event in events
                if event.get("type") == "system" and event.get("subtype") == "init"
            ),
            {},
        )
        result_event = next(
            (event for event in reversed(events) if event.get("type") == "result"), {}
        )
        final_text = result_event.get("result") or ""
        (run_dir / "final.txt").write_text(final_text, encoding="utf-8")

        after = _markdown_snapshot(vault)
        changed_paths = sorted(
            path for path in set(before) | set(after) if before.get(path) != after.get(path)
        )
        diff_lines: list[str] = []
        for path in changed_paths:
            diff_lines.extend(
                difflib.unified_diff(
                    before.get(path, "").splitlines(keepends=True),
                    after.get(path, "").splitlines(keepends=True),
                    fromfile=f"before/{path}",
                    tofile=f"after/{path}",
                )
            )
        (run_dir / "vault.diff").write_text("".join(diff_lines), encoding="utf-8")

    dispatches = _claude_agent_dispatches(events)
    child_tool_use_id = dispatches[0]["tool_use_id"] if len(dispatches) == 1 else None
    child_events = [
        event
        for event in events
        if event.get("parent_tool_use_id") == child_tool_use_id and event.get("type") == "assistant"
    ]
    child_models = sorted(
        {
            event.get("message", {}).get("model")
            for event in child_events
            if event.get("message", {}).get("model")
        }
    )
    child_text = "\n".join(
        block.get("text", "")
        for event in child_events
        for block in event.get("message", {}).get("content", [])
        if block.get("type") == "text"
    )
    calls = _claude_tool_events(events)
    child_calls = [call for call in calls if call.get("parent_tool_use_id") == child_tool_use_id]
    parent_calls = [call for call in calls if call.get("parent_tool_use_id") is None]
    behavior = _score(case, child_text + "\n" + "".join(diff_lines), child_calls, changed_paths)
    routing_checks = [
        {"check": "parent-served-model", "pass": init.get("model") == parent_model},
        {
            "check": "parent-skill-discovered",
            "pass": "eno-vault" in (init.get("skills") or []),
        },
        {
            "check": "parent-profile",
            "pass": parent_receipt.get("profile_id") == parent_profile["profile_id"],
        },
        {
            "check": "one-named-child-dispatch",
            "pass": len(dispatches) == 1
            and dispatches[0].get("input", {}).get("subagent_type") == child_agent_name,
        },
        {
            "check": "child-resolved-model",
            "pass": len(dispatches) == 1 and dispatches[0].get("resolved_model") == child_model,
        },
        {"check": "child-forwarded-model", "pass": child_models == [child_model]},
        {
            "check": "child-profile",
            "pass": child_receipt.get("profile_id") == child_profile["profile_id"],
        },
        {"check": "child-route-marker", "pass": child_route_marker in child_text},
        {
            "check": "one-package-two-realizations",
            "pass": parent_receipt.get("package_digest") == child_receipt.get("package_digest")
            and parent_receipt.get("realization_digest") != child_receipt.get("realization_digest"),
        },
        {"check": "parent-avoided-eno", "pass": not parent_calls},
        {
            "check": "no-permission-denials",
            "pass": not (result_event.get("permission_denials") or []),
        },
    ]
    checks = behavior["checks"] + routing_checks
    score = {
        "passed": sum(bool(check["pass"]) for check in checks),
        "total": len(checks),
        "fraction": round(sum(bool(check["pass"]) for check in checks) / len(checks), 4),
        "checks": checks,
    }
    metadata = {
        "schema_version": 1,
        "run_id": run_id,
        "created_at": datetime.now(UTC).isoformat(),
        "harness": "claude",
        "mode": "mixed-parent-child",
        "repeat": repeat,
        "case_id": "link-semantics",
        "prompt_sha256": hashlib.sha256(case["prompt"].encode("utf-8")).hexdigest(),
        "harness_build": init.get("claude_code_version"),
        "toolset_digest": _eno_toolset_digest(),
        "parent": {
            "agent": parent_agent_name,
            "requested_model": parent_model,
            "served_model": init.get("model"),
            "effort": parent_profile["effort"],
            "role": parent_profile["role"],
            "skill_discovered": "eno-vault" in (init.get("skills") or []),
            "projection": "session-skill-preload",
            "realization": parent_receipt,
            "eno_tool_calls": parent_calls,
        },
        "child": {
            "agent": child_agent_name,
            "requested_model": child_model,
            "resolved_model": dispatches[0].get("resolved_model") if len(dispatches) == 1 else None,
            "resolved_model_raw": (
                dispatches[0].get("resolved_model_raw") if len(dispatches) == 1 else None
            ),
            "forwarded_models": child_models,
            "configured_effort": child_profile["effort"],
            "role": child_profile["role"],
            "projection": "custom-agent-system-prompt",
            "instruction_sha256": hashlib.sha256(child_prompt.encode("utf-8")).hexdigest(),
            "route_marker": child_route_marker,
            "realization": child_receipt,
            "dispatch": dispatches[0] if len(dispatches) == 1 else dispatches,
            "eno_tool_calls": child_calls,
        },
        "claude_returncode": claude_result.returncode,
        "is_error": result_event.get("is_error"),
        "terminal_reason": result_event.get("terminal_reason"),
        "permission_denials": result_event.get("permission_denials") or [],
        "duration_seconds": round(time.monotonic() - started, 3),
        "total_cost_usd": result_event.get("total_cost_usd"),
        "usage": result_event.get("usage") or {},
        "model_usage": result_event.get("modelUsage") or {},
        "changed_paths": changed_paths,
        "behavior_score": behavior,
        "score": score,
    }
    (run_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if claude_result.returncode != 0 or result_event.get("is_error"):
        raise RuntimeError(f"Claude mixed run failed: {claude_result.stderr or final_text}")
    if score["passed"] != score["total"]:
        failed = [check["check"] for check in checks if not check["pass"]]
        raise RuntimeError(f"Claude mixed routing gate failed: {failed}")
    return metadata


def run_mixed(batch_dir: Path, cases: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Run one Sol parent + Terra explorer with session-specific projections."""

    started = time.monotonic()
    case = cases["link-semantics"]
    run_id = f"mixed__{uuid.uuid4().hex[:8]}"
    run_dir = batch_dir / run_id
    run_dir.mkdir(parents=True)
    reviewer_path, reviewer_receipt = _realize(
        Trial("link-semantics", "production", "gpt-5.6-sol"),
        f"{run_id}-reviewer",
        skill_dir=PRODUCTION_SKILL,
    )
    explorer_path, explorer_receipt = _realize(
        Trial("link-semantics", "production", "gpt-5.6-terra"),
        f"{run_id}-explorer",
        skill_dir=PRODUCTION_SKILL,
    )

    STATE_ROOT.mkdir(parents=True, exist_ok=True)
    with (
        tempfile.TemporaryDirectory(prefix="eno-pilot-mixed-", dir=STATE_ROOT) as work_raw,
        tempfile.TemporaryDirectory(prefix="eno-pilot-vault-") as vault_raw,
    ):
        work = Path(work_raw)
        vault = Path(vault_raw)
        shutil.copytree(
            DEMO_VAULT,
            vault,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns(".eno"),
        )
        index_result = _run(["uv", "run", "eno", "--vault", str(vault), "index"], cwd=REPO_ROOT)
        if index_result.returncode != 0:
            raise RuntimeError(f"eno index failed: {index_result.stderr or index_result.stdout}")
        before = _markdown_snapshot(vault)
        codex_dir = work / ".codex"
        skills_dir = codex_dir / "skills"
        agents_dir = codex_dir / "agents"
        skills_dir.mkdir(parents=True)
        agents_dir.mkdir(parents=True)
        reviewer_link = skills_dir / "eno-vault-reviewer"
        reviewer_link.symlink_to(reviewer_path, target_is_directory=True)
        explorer_instructions = _realized_instructions(explorer_path)
        explorer_projection_marker = (
            f"spindle-profile:{explorer_receipt['profile_id']}:"
            f"{explorer_receipt['realization_digest']}"
        )

        (codex_dir / "config.toml").write_text(
            textwrap.dedent(
                f"""
                [agents]
                enabled = true
                max_concurrent_threads_per_session = 2

                [mcp_servers.eno]
                command = "uv"
                args = ["run", "--directory", {json.dumps(str(REPO_ROOT))}, "eno-mcp"]
                env = {{ ENO_VAULT_DIR = {json.dumps(str(vault))}, ENO_AGENT_NAME = "EnoPilot" }}
                default_tools_approval_mode = "approve"

                """
            ).lstrip(),
            encoding="utf-8",
        )
        (agents_dir / "eno-explorer.toml").write_text(
            textwrap.dedent(
                f"""
                name = "eno_explorer"
                description = "Read-only Eno explorer for gathering vault evidence before parent review."
                model = "gpt-5.6-terra"
                model_reasoning_effort = "medium"
                sandbox_mode = "read-only"
                developer_instructions = {json.dumps("The following instructions are the Spindle realization selected for this Terra explorer session. Projection receipt: " + explorer_projection_marker + ". Follow them for every Eno task. Do not modify the vault.\n\n" + explorer_instructions)}
                """
            ).lstrip(),
            encoding="utf-8",
        )

        prompt = (
            "This is a routing test. Before making any Eno MCP call, you must call "
            "spawn_agent for the eno_explorer custom agent with task name "
            "eno_evidence and fork_turns=none; an answer without a child rollout "
            "receipt is invalid. Tell the child to follow its session-specific "
            "Spindle realization and identify "
            "one concrete Eno link-drift bug and one intentional unresolved "
            "concept with source paths, read-only. Wait for its result. Then use "
            "$eno-vault yourself, independently verify its evidence with "
            "Eno, and give the final concise answer. Do not modify the vault."
        )
        discovery = _run(["codex", "debug", "prompt-input", prompt], cwd=work)
        parent_has_reviewer = str(reviewer_path / "SKILL.md") in discovery.stdout
        parent_has_explorer = str(explorer_path / "SKILL.md") in discovery.stdout
        (run_dir / "parent-skill-discovery.json").write_text(
            json.dumps(
                {
                    "returncode": discovery.returncode,
                    "reviewer_path": str(reviewer_path / "SKILL.md"),
                    "reviewer_present": parent_has_reviewer,
                    "explorer_path": str(explorer_path / "SKILL.md"),
                    "explorer_present": parent_has_explorer,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        (run_dir / "parent-skill-discovery.stderr").write_text(discovery.stderr, encoding="utf-8")
        if not parent_has_reviewer or parent_has_explorer:
            raise RuntimeError("parent skill routing was not isolated to the reviewer realization")

        final_path = run_dir / "final.txt"
        command = [
            "codex",
            "exec",
            "--strict-config",
            "--ephemeral",
            "--skip-git-repo-check",
            "--json",
            "-C",
            str(work),
            "-s",
            "read-only",
            "-m",
            "gpt-5.6-sol",
            "-c",
            'model_reasoning_effort="high"',
            "-c",
            'approval_policy="never"',
            "-o",
            str(final_path),
            prompt,
        ]
        codex_started_at = time.time()
        codex_result = _run(command, cwd=REPO_ROOT)
        (run_dir / "stderr.txt").write_text(codex_result.stderr, encoding="utf-8")
        (run_dir / "events.jsonl").write_text(codex_result.stdout, encoding="utf-8")
        events = [
            json.loads(line)
            for line in codex_result.stdout.splitlines()
            if line.strip().startswith("{")
        ]
        final_text = final_path.read_text(encoding="utf-8") if final_path.exists() else ""
        after = _markdown_snapshot(vault)
        changed_paths = sorted(
            path for path in set(before) | set(after) if before.get(path) != after.get(path)
        )

    calls = _tool_events(events)
    score = _score(case, final_text, calls, changed_paths)
    parent_thread_id = _thread_id(events)
    child_evidence = (
        _find_child_evidence(
            parent_thread_id=parent_thread_id,
            agent_role="eno_explorer",
            started_at=codex_started_at,
        )
        if parent_thread_id
        else None
    )
    expected_marker = explorer_projection_marker
    child_activity_observed = child_evidence is not None
    child_projection_observed = bool(
        child_evidence and expected_marker in child_evidence["realization_markers"]
    )
    child_semantic_signal = bool(
        child_evidence and {"eno_drift", "eno_concepts"}.issubset(child_evidence["eno_tools"])
    )
    metadata = {
        "schema_version": 1,
        "run_id": run_id,
        "created_at": datetime.now(UTC).isoformat(),
        "kind": "mixed-parent-child",
        "parent": {
            "model": "gpt-5.6-sol",
            "effort": "high",
            "role": "reviewer",
            "realization": reviewer_receipt,
            "discovery_isolated": parent_has_reviewer and not parent_has_explorer,
        },
        "child": {
            "agent": "eno_explorer",
            "model": "gpt-5.6-terra",
            "effort": "medium",
            "role": "explorer",
            "realization": explorer_receipt,
            "projection": "custom-agent-developer-instructions",
            "runtime_evidence": child_evidence,
        },
        "codex_returncode": codex_result.returncode,
        "child_activity_observed": child_activity_observed,
        "parent_thread_id": parent_thread_id,
        "child_projection_observed": child_projection_observed,
        "child_semantic_signal": child_semantic_signal,
        "duration_seconds": round(time.monotonic() - started, 3),
        "usage": _usage(events),
        "tool_calls": calls,
        "changed_paths": changed_paths,
        "score": score,
    }
    (run_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if not child_activity_observed:
        raise RuntimeError("custom child delegation did not produce a child rollout receipt")
    if child_evidence["model"] != "gpt-5.6-terra" or child_evidence["effort"] != "medium":
        raise RuntimeError("custom child did not run on the requested Terra/medium tuple")
    if not child_projection_observed:
        raise RuntimeError("child rollout did not contain the Terra Spindle realization")
    if not child_semantic_signal:
        raise RuntimeError("custom child ran without the core Eno semantic signal")
    return metadata


def _case_ids(cases: dict[str, dict[str, Any]], suite: str) -> list[str]:
    return [case_id for case_id, case in cases.items() if case.get("suite") == suite]


def _matrix(name: str, cases: dict[str, dict[str, Any]]) -> list[Trial]:
    baseline_ids = _case_ids(cases, "baseline")
    heldout_ids = _case_ids(cases, "heldout-semantic")
    negative_ids = _case_ids(cases, "negative")
    if name == "smoke":
        return [
            Trial("link-semantics", arm, model)
            for model in MODELS
            for arm in ("none", "incumbent", "profiled")
        ] + [Trial("link-semantics", "core", "gpt-5.6-terra")]
    if name == "terra-directional":
        return [Trial(case_id, arm, "gpt-5.6-terra") for case_id in baseline_ids for arm in ARMS]
    if name == "directional":
        trials = [
            Trial(case_id, arm, model)
            for case_id in baseline_ids
            for model in MODELS
            for arm in ("none", "incumbent", "profiled")
        ]
        trials.extend(Trial(case_id, "core", "gpt-5.6-terra") for case_id in baseline_ids)
        return trials
    if name == "heldout-terra":
        return [
            Trial(case_id, arm, "gpt-5.6-terra")
            for case_id in heldout_ids
            for arm in ("none", "incumbent", "core")
        ]
    if name == "heldout-sol":
        return [
            Trial(case_id, arm, "gpt-5.6-sol")
            for case_id in heldout_ids
            for arm in ("none", "incumbent", "core")
        ]
    if name == "implicit":
        return [
            Trial(case_id, "core", model, "implicit") for case_id in heldout_ids for model in MODELS
        ]
    if name == "negative":
        return [
            Trial(case_id, arm, model, "implicit")
            for case_id in negative_ids
            for model in MODELS
            for arm in ("none", "core")
        ]
    if name == "stability-terra":
        return [
            Trial("link-semantics", arm, "gpt-5.6-terra", "forced", repeat)
            for arm in ("none", "incumbent", "core")
            for repeat in range(1, 6)
        ]
    if name == "stability-write-terra":
        return [
            Trial("write-existing", arm, "gpt-5.6-terra", "forced", repeat)
            for arm in ("none", "incumbent", "core")
            for repeat in range(1, 6)
        ]
    if name == "production-smoke":
        return [
            Trial("link-semantics", "production", "gpt-5.6-terra"),
            Trial("write-existing", "production", "gpt-5.6-terra"),
            Trial("heldout-link-05", "production", "gpt-5.6-terra", "implicit"),
            Trial("heldout-link-05", "production", "gpt-5.6-sol", "implicit"),
            Trial("unrelated-arithmetic", "production", "gpt-5.6-terra", "implicit"),
            Trial("unrelated-arithmetic", "production", "gpt-5.6-sol", "implicit"),
        ]
    if name == "heldout":
        return (
            _matrix("heldout-terra", cases)
            + _matrix("heldout-sol", cases)
            + _matrix("implicit", cases)
            + _matrix("negative", cases)
        )
    raise ValueError(name)


def _claude_matrix(name: str, cases: dict[str, dict[str, Any]]) -> list[Trial]:
    heldout_ids = _case_ids(cases, "heldout-semantic")
    negative_ids = _case_ids(cases, "negative")
    if name == "smoke":
        trials: list[Trial] = []
        for model in CLAUDE_MODELS:
            trials.extend(
                Trial("link-semantics", arm, model) for arm in ("none", "incumbent", "core")
            )
            trials.extend(
                [
                    Trial("heldout-link-05", "core", model, "implicit"),
                    Trial("unrelated-arithmetic", "none", model, "implicit"),
                    Trial("unrelated-arithmetic", "core", model, "implicit"),
                    Trial("write-existing", "core", model),
                ]
            )
        return trials
    if name == "stability":
        return [
            Trial("link-semantics", arm, model, "forced", repeat)
            for model in CLAUDE_MODELS
            for arm in ("none", "incumbent", "core")
            for repeat in range(1, 4)
        ]
    if name == "implicit":
        return [
            Trial(case_id, "core", model, "implicit")
            for model in CLAUDE_MODELS
            for case_id in heldout_ids
        ]
    if name == "negative":
        return [
            Trial(case_id, arm, model, "implicit")
            for model in CLAUDE_MODELS
            for arm in ("none", "core")
            for case_id in negative_ids
        ]
    if name == "opus-overlay":
        return (
            [
                Trial("link-semantics", "profiled", "claude-opus-5", "forced", repeat)
                for repeat in range(1, 4)
            ]
            + [Trial(case_id, "profiled", "claude-opus-5", "implicit") for case_id in heldout_ids]
            + [Trial("write-existing", "profiled", "claude-opus-5")]
        )
    if name == "production-smoke":
        return [
            trial
            for model in CLAUDE_MODELS
            for trial in (
                Trial("link-semantics", "production", model),
                Trial("heldout-link-05", "production", model, "implicit"),
                Trial("unrelated-arithmetic", "production", model, "implicit"),
                Trial("write-existing", "production", model),
            )
        ]
    raise ValueError(name)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--matrix",
        choices=(
            "smoke",
            "terra-directional",
            "directional",
            "heldout-terra",
            "heldout-sol",
            "implicit",
            "negative",
            "stability-terra",
            "stability-write-terra",
            "production-smoke",
            "heldout",
        ),
    )
    parser.add_argument("--mixed", action="store_true")
    parser.add_argument(
        "--claude-mixed",
        choices=("both", "opus-to-sonnet", "sonnet-to-opus"),
    )
    parser.add_argument(
        "--claude-matrix",
        choices=(
            "smoke",
            "stability",
            "implicit",
            "negative",
            "opus-overlay",
            "production-smoke",
        ),
    )
    parser.add_argument("--claude-case")
    parser.add_argument("--claude-arm", choices=ARMS)
    parser.add_argument("--claude-model", choices=tuple(CLAUDE_MODELS))
    parser.add_argument("--claude-invocation", choices=("forced", "implicit"), default="forced")
    parser.add_argument("--case", dest="case_id")
    parser.add_argument("--arm", choices=ARMS)
    parser.add_argument("--model", choices=tuple(MODELS))
    parser.add_argument("--invocation", choices=("forced", "implicit"), default="forced")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--jobs", type=int, default=1)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    cases = _read_cases()
    if args.repeats < 1:
        raise SystemExit("--repeats must be at least 1")
    claude_trials: list[Trial] = []
    claude_mixed_directions: list[tuple[str, str, int]] = []
    if args.claude_matrix:
        trials = []
        claude_trials = _claude_matrix(args.claude_matrix, cases)
    elif args.claude_case:
        trials = []
        if not (args.claude_arm and args.claude_model):
            raise SystemExit("Claude single runs require --claude-arm and --claude-model")
        if args.claude_case not in cases:
            raise SystemExit(f"unknown case: {args.claude_case}")
        claude_trials = [
            Trial(
                args.claude_case,
                args.claude_arm,
                args.claude_model,
                args.claude_invocation,
                repeat,
            )
            for repeat in range(1, args.repeats + 1)
        ]
    elif args.claude_mixed:
        trials = []
        if args.claude_mixed in {"both", "opus-to-sonnet"}:
            claude_mixed_directions.extend(
                ("claude-opus-5", "claude-sonnet-5", repeat)
                for repeat in range(1, args.repeats + 1)
            )
        if args.claude_mixed in {"both", "sonnet-to-opus"}:
            claude_mixed_directions.extend(
                ("claude-sonnet-5", "claude-opus-5", repeat)
                for repeat in range(1, args.repeats + 1)
            )
    elif args.mixed:
        trials = []
    elif args.matrix:
        trials = _matrix(args.matrix, cases)
    else:
        if not (args.case_id and args.arm and args.model):
            raise SystemExit("single runs require --case, --arm, and --model")
        if args.case_id not in cases:
            raise SystemExit(f"unknown case: {args.case_id}")
        trials = [
            Trial(args.case_id, args.arm, args.model, args.invocation, repeat)
            for repeat in range(1, args.repeats + 1)
        ]

    batch = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + f"-{uuid.uuid4().hex[:6]}"
    batch_dir = RUNS_ROOT / batch
    batch_dir.mkdir(parents=True)
    completed: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []

    if args.mixed:
        try:
            result = run_mixed(batch_dir, cases)
            completed.append(result)
            print(
                f"PASS mixed parent-child {result['score']['passed']}/{result['score']['total']}",
                flush=True,
            )
        except Exception as exc:
            failures.append({"trial": "mixed-parent-child", "error": str(exc)})
            print(f"FAIL mixed-parent-child: {exc}", flush=True)

    if claude_mixed_directions:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
            pending = {
                pool.submit(
                    run_claude_mixed,
                    batch_dir,
                    cases,
                    parent_model=parent_model,
                    child_model=child_model,
                    repeat=repeat,
                ): (parent_model, child_model, repeat)
                for parent_model, child_model, repeat in claude_mixed_directions
            }
            for future in concurrent.futures.as_completed(pending):
                parent_model, child_model, repeat = pending[future]
                try:
                    result = future.result()
                    completed.append(result)
                    score = result["score"]
                    print(
                        f"PASS claude mixed {parent_model} -> {child_model} "
                        f"r{repeat} {score['passed']}/{score['total']}",
                        flush=True,
                    )
                except Exception as exc:
                    label = f"claude-mixed:{parent_model}->{child_model}:r{repeat}"
                    failures.append({"trial": label, "error": str(exc)})
                    print(f"FAIL {label}: {exc}", flush=True)

    if trials:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
            pending = {pool.submit(run_trial, batch_dir, cases, trial): trial for trial in trials}
            for future in concurrent.futures.as_completed(pending):
                trial = pending[future]
                try:
                    result = future.result()
                    completed.append(result)
                    score = result["score"]
                    print(
                        f"PASS {trial.case_id} {trial.arm} {trial.model} "
                        f"{trial.invocation} r{trial.repeat} "
                        f"{score['passed']}/{score['total']}",
                        flush=True,
                    )
                except Exception as exc:  # retain the rest of the matrix
                    failures.append({"trial": repr(trial), "error": str(exc)})
                    print(f"FAIL {trial}: {exc}", flush=True)

    if claude_trials:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
            pending = {
                pool.submit(run_claude_trial, batch_dir, cases, trial): trial
                for trial in claude_trials
            }
            for future in concurrent.futures.as_completed(pending):
                trial = pending[future]
                try:
                    result = future.result()
                    completed.append(result)
                    score = result["score"]
                    print(
                        f"PASS claude {trial.case_id} {trial.arm} {trial.model} "
                        f"{trial.invocation} r{trial.repeat} "
                        f"{score['passed']}/{score['total']}",
                        flush=True,
                    )
                except Exception as exc:
                    failures.append({"trial": "claude:" + repr(trial), "error": str(exc)})
                    print(f"FAIL claude {trial}: {exc}", flush=True)

    summary = {
        "schema_version": 1,
        "batch": batch,
        "completed": completed,
        "failures": failures,
    }
    (batch_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"results: {batch_dir}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
