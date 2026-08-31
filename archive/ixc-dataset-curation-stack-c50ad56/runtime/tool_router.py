from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Protocol

from infra.metering import MeterEmitter
from infra.plans import PlanStore
from infra.budget import BudgetTracker
from infra.policy_gates import PolicyGateEnforcer


class ToolRouterError(RuntimeError):
    pass


@dataclass(frozen=True)
class ModelResult:
    model_id: str
    model_class: str
    output: Any
    duration_ms: int


class ModelProvider(Protocol):
    """Pluggable model provider interface."""

    def invoke(self, *, model_id: str, model_class: str, payload: Dict[str, Any]) -> Any: ...


class LocalMockModelProvider:
    """Deterministic local model provider (stdlib-only).

    This exists so ToolRouter can be exercised end-to-end without external dependencies.
    """

    def invoke(self, *, model_id: str, model_class: str, payload: Dict[str, Any]) -> Any:
        text = payload.get("text")
        task = payload.get("task") or ""
        if isinstance(text, str):
            s = text.strip().replace("\n", " ")
            return {
                "task": task,
                "summary": s[:200],
                "chars_in": len(text),
                "model_id": model_id,
                "model_class": model_class,
            }
        return {
            "task": task,
            "echo": json.dumps(payload, ensure_ascii=False, sort_keys=True),
            "model_id": model_id,
            "model_class": model_class,
        }


class OpenAIProviderUnavailable(ToolRouterError):
    pass


class OpenAIChatCompletionsProvider:
    """Optional provider shim.

    This repo is stdlib-only by default. If you want a real provider:
      - install openai (or your chosen client)
      - set OPENAI_API_KEY
      - set IXO_MODEL_PROVIDER=openai

    NOTE: This class intentionally fails fast if dependencies are missing.
    """

    def __init__(self) -> None:
        try:
            import openai  # type: ignore
        except Exception as e:  # pragma: no cover
            raise OpenAIProviderUnavailable(
                "OpenAI provider selected but 'openai' package is not installed. "
                "Install it and configure OPENAI_API_KEY."
            ) from e
        if not os.environ.get("OPENAI_API_KEY"):  # pragma: no cover
            raise OpenAIProviderUnavailable("OPENAI_API_KEY is not set.")
        self._openai = openai

    def invoke(self, *, model_id: str, model_class: str, payload: Dict[str, Any]) -> Any:  # pragma: no cover
        # Minimal illustrative call shape. Adjust for your client version.
        # Payload expected: {"messages":[{"role":"user","content":"..."}], "temperature":0.2, ...}
        messages = payload.get("messages")
        if not isinstance(messages, list):
            # Back-compat: allow {"text": "..."}
            text = payload.get("text")
            if isinstance(text, str):
                messages = [{"role": "user", "content": text}]
            else:
                raise ToolRouterError("OpenAI provider requires payload.messages (list) or payload.text (str).")

        resp = self._openai.chat.completions.create(
            model=model_id,
            messages=messages,
            temperature=payload.get("temperature", 0.2),
        )
        # Return a compact, JSON-serializable shape
        out_text = resp.choices[0].message.content if resp.choices else ""
        return {"text": out_text, "model_id": model_id, "model_class": model_class}


def _default_model_id_for_class(model_class: str) -> str:
    mc = str(model_class or "cheap")
    if mc == "reasoning":
        return "mock-reasoning"
    if mc == "transform":
        return "mock-transform"
    return "mock-cheap"


def _provider_from_env() -> ModelProvider:
    provider = (os.environ.get("IXO_MODEL_PROVIDER") or "mock").strip().lower()
    if provider in ("mock", "local", "local-mock"):
        return LocalMockModelProvider()
    if provider in ("openai", "openai-chat"):
        return OpenAIChatCompletionsProvider()
    raise ToolRouterError(f"Unknown IXO_MODEL_PROVIDER: {provider}")


class ToolRouter:
    """Centralized invocation boundary for models and tools.

    Responsibilities:
      - enforce policy gates at pre/post tool call
      - emit metering for every invocation
      - provide a single seam for future LLM/tool integrations
    """

    def __init__(
        self,
        *,
        agent_name: str,
        context: Dict[str, Any],
        policy: PolicyGateEnforcer,
        meter: MeterEmitter,
        provider: Optional[ModelProvider] = None,
        repo_root: str = ".",
    ):
        self.agent_name = agent_name
        self.context = context
        self.policy = policy
        self.meter = meter
        self.provider = provider or _provider_from_env()
        self.plan_store = PlanStore(repo_root=repo_root)
        self.budget = BudgetTracker(repo_root=repo_root)
        self.repo_root = repo_root

    
def _credits_for_model_call(self, model_class: str) -> float:
    tenant_id = str(self.context.get("tenant_id") or "")
    plan_id = self.plan_store.tenant_plan_id(tenant_id)
    plan = self.plan_store.plan(plan_id) if plan_id else {}
    pricing = (plan.get("pricing") or {})
    table = (pricing.get("credits_per_model_call_by_class") or {})
    try:
        return float(table.get(str(model_class), 0.0) or 0.0)
    except Exception:
        return 0.0

def _credits_for_tool_call(self, tool_name: str) -> float:
    tenant_id = str(self.context.get("tenant_id") or "")
    plan_id = self.plan_store.tenant_plan_id(tenant_id)
    plan = self.plan_store.plan(plan_id) if plan_id else {}
    pricing = (plan.get("pricing") or {})
    table = (pricing.get("credits_per_tool_call_by_name") or {})
    try:
        return float(table.get(str(tool_name), 0.0) or 0.0)
    except Exception:
        return 0.0

def _budget_cfg(self) -> Dict[str, Any]:
    tenant_id = str(self.context.get("tenant_id") or "")
    plan_id = self.plan_store.tenant_plan_id(tenant_id)
    plan = self.plan_store.plan(plan_id) if plan_id else {}
    return plan.get("budget", {}) or {}
def _resolve_model_id(self, model_class: str) -> str:
        overrides = ((self.context.get("execution") or {}).get("model_overrides") or {})
        if isinstance(overrides, dict):
            ov = overrides.get(self.agent_name)
            if isinstance(ov, str) and ov.strip():
                return ov.strip()

        # Optional mapping via env (JSON): IXO_MODEL_ID_BY_CLASS='{"cheap":"gpt-4o-mini","transform":"gpt-4o-mini"}'
        raw = os.environ.get("IXO_MODEL_ID_BY_CLASS")
        if raw:
            try:
                mp = json.loads(raw)
                if isinstance(mp, dict):
                    v = mp.get(str(model_class))
                    if isinstance(v, str) and v.strip():
                        return v.strip()
            except Exception:
                pass

        return _default_model_id_for_class(model_class)

    
    def invoke_model(self, *, model_class: str, payload: Dict[str, Any], model_id: Optional[str] = None) -> ModelResult:
            # Budget-aware model selection with optional degradation.
            requested_class = str(model_class or "cheap")
            tenant_id = str(self.context.get("tenant_id") or "")
            budget_cfg = self._budget_cfg()
            max_credits = float(budget_cfg.get("credits_per_day", 0.0) or 0.0)
            strategy = (os.environ.get("IXO_BUDGET_STRATEGY") or "degrade").strip().lower()

            # Candidate classes in descending-to-cheap order for degradation
            order = ["reasoning", "transform", "cheap"]
            if requested_class not in order:
                requested_class = "cheap"
            candidates = [requested_class] + [c for c in order if c != requested_class]
            # Try requested first, then cheaper ones
            candidates = [c for c in candidates if order.index(c) >= order.index(requested_class)]

            selected_class = requested_class
            reserved = False

            if max_credits > 0.0 and tenant_id:
                from datetime import date
                for c in candidates:
                    cost = self._credits_for_model_call(c)
                    ok, _usage = self.budget.try_reserve(
                        tenant_id=tenant_id,
                        day=date.today(),
                        credits=cost,
                        max_credits=max_credits,
                    )
                    if ok:
                        selected_class = c
                        reserved = True
                        if c != requested_class:
                            # record degradation
                            self.meter.emit(
                                "budget_degrade",
                                count=1,
                                labels={"agent_name": self.agent_name, "from_model_class": requested_class, "to_model_class": c},
                            )
                        break

                if not reserved:
                    if strategy == "deny":
                        raise ToolRouterError("budget_exceeded: no remaining credits for model call")
                    # degrade strategy but nothing fits
                    raise ToolRouterError("budget_exceeded: cannot degrade further")

            # Resolve model id after selecting class
            mid = model_id or self._resolve_model_id(selected_class)
            start = time.time()

            gate_ctx = dict(self.context or {})
            gate_ctx.update(
                {
                    "agent_name": self.agent_name,
                    "call_type": "model",
                    "model_class": selected_class,
                    "model_id": mid,
                }
            )
            self.policy.enforce("pre_tool_call", gate_ctx)

            out = self.provider.invoke(model_id=mid, model_class=selected_class, payload=payload)

            dur_ms = int((time.time() - start) * 1000)

            post_ctx = dict(gate_ctx)
            post_ctx["duration_ms"] = dur_ms
            self.policy.enforce("post_tool_call", post_ctx)

            self.meter.emit(
                "model_call",
                count=1,
                labels={"agent_name": self.agent_name, "model_class": selected_class, "model_id": mid},
            )

            return ModelResult(model_id=mid, model_class=selected_class, output=out, duration_ms=dur_ms)

     for c in candidates:
                cost = self._credits_for_model_call(c)
                ok, _usage = self.budget.try_reserve(
                    tenant_id=tenant_id,
                    day=date.today(),
                    credits=cost,
                    max_credits=max_credits,
                )
                if ok:
                    selected_class = c
                    reserved = True
                    if c != requested_class:
                        # record degradation
                        self.meter.emit(
                            "budget_degrade",
                            count=1,
                            labels={"agent_name": self.agent_name, "from_model_class": requested_class, "to_model_class": c},
                        )
                    break

            if not reserved:
                if strategy == "deny":
                    raise ToolRouterError("budget_exceeded: no remaining credits for model call")
                # degrade strategy but nothing fits
                raise ToolRouterError("budget_exceeded: cannot degrade further")

        # Resolve model id after selecting class
        mid = model_id or self._resolve_model_id(selected_class)
        start = time.time()

        gate_ctx = dict(self.context or {})
        gate_ctx.update(
            {
                "agent_name": self.agent_name,
                "call_type": "model",
                "model_class": selected_class,
                "model_id": mid,
            }
        )
        self.policy.enforce("pre_tool_call", gate_ctx)

        out = self.provider.invoke(model_id=mid, model_class=selected_class, payload=payload)

        dur_ms = int((time.time() - start) * 1000)

        post_ctx = dict(gate_ctx)
        post_ctx["duration_ms"] = dur_ms
        self.policy.enforce("post_tool_call", post_ctx)

        self.meter.emit(
            "model_call",
            count=1,
            labels={"agent_name": self.agent_name, "model_class": selected_class, "model_id": mid},
        )

        return ModelResult(model_id=mid, model_class=selected_class, output=out, duration_ms=dur_ms)

    
    def invoke_tool(self, *, tool_name: str, payload: Dict[str, Any]) -> Dict[str, Any]:
            start = time.time()
            gate_ctx = dict(self.context or {})
            gate_ctx.update({"agent_name": self.agent_name, "call_type": "tool", "tool_name": tool_name})
            self.policy.enforce("pre_tool_call", gate_ctx)

            # Budget guardrail (credits) for tool calls
            tenant_id = str(self.context.get("tenant_id") or "")
            budget_cfg = self._budget_cfg()
            max_credits = float(budget_cfg.get("credits_per_day", 0.0) or 0.0)
            if max_credits > 0.0 and tenant_id:
                from datetime import date
                cost = self._credits_for_tool_call(tool_name)
                ok, _usage = self.budget.try_reserve(
                    tenant_id=tenant_id,
                    day=date.today(),
                    credits=cost,
                    max_credits=max_credits,
                )
                if not ok:
                    raise ToolRouterError("budget_exceeded: no remaining credits for tool call")

            # Built-in deterministic tools (v1)
            if tool_name == "hash_sha256":
                b = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
                import hashlib

                out = {"sha256": hashlib.sha256(b).hexdigest()}
            elif tool_name == "json_validate":
                try:
                    json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
                    out = {"ok": True}
                except Exception as e:
                    out = {"ok": False, "error": str(e)}
            else:
                raise ToolRouterError(f"Unknown tool: {tool_name}")

            dur_ms = int((time.time() - start) * 1000)
            post_ctx = dict(gate_ctx)
            post_ctx["duration_ms"] = dur_ms
            self.policy.enforce("post_tool_call", post_ctx)

            self.meter.emit("tool_call", count=1, labels={"agent_name": self.agent_name, "tool_name": tool_name})
            return out
