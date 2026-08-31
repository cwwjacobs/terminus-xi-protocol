import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from infra.tenancy import scope_path
from runtime.context_manager import ContextManager


class PolicyViolation(RuntimeError):
    pass


@dataclass(frozen=True)
class PolicyDecision:
    gate: str
    allow: bool
    reason: str
    policy_profile_id: str
    details: Optional[Dict[str, Any]] = None


def _stable_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class PolicyEngine:
    """Deterministic policy engine (v1+).

    Precedence:
      1) Tenant override: .tenants/<tenant_id>/policies/<policy_profile_id>.json
      2) Built-in spec: specs/policies/<policy_profile_id>.json
      3) Built-in default: specs/policies/default.json

    Supported schema formats:
      - v1 list format (preferred):
          {"id":"...","rules":[{"type":"require_fields",...}, ...]}
      - legacy dict format (back-compat):
          {"id":"...","rules":{"require_fields":[...],"deny_if":[...],"max_bytes_field":{...}}}

    Rule types (list format):
      - require_fields: fields=[...]
      - allow_execution_modes: modes=[...]
      - deny_execution_modes: modes=[...]
      - allow_graph_ids: graph_ids=[...]
      - allow_model_classes: classes=[...]
      - max_payload_bytes: event="pre_exec" max=<int> (compares ctx["payload_bytes_in"])
      - allow_all: always allow (terminal)
    """

    def __init__(self, repo_root: str = "."):
        self.repo_root = repo_root

    def _load_json(self, path: str) -> Optional[Dict[str, Any]]:
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def load_profile(self, tenant_id: str, policy_profile_id: str) -> Dict[str, Any]:
        tenant_path = os.path.join(self.repo_root, scope_path(tenant_id, "policies", f"{policy_profile_id}.json"))
        spec_path = os.path.join(self.repo_root, "specs", "policies", f"{policy_profile_id}.json")
        default_path = os.path.join(self.repo_root, "specs", "policies", "default.json")

        profile = self._load_json(tenant_path) or self._load_json(spec_path) or self._load_json(default_path)
        if profile is None:
            profile = {"id": "default", "version": "1", "rules": [{"type": "allow_all"}]}

        if "id" not in profile:
            profile["id"] = policy_profile_id
        if "rules" not in profile:
            profile["rules"] = []
        return profile

    def _normalize_rules(self, rules: Any) -> List[Dict[str, Any]]:
        # Preferred: list of rule dicts
        if isinstance(rules, list):
            return [r for r in rules if isinstance(r, dict)]

        # Legacy: dict of rule collections
        if isinstance(rules, dict):
            out: List[Dict[str, Any]] = []
            req = rules.get("require_fields") or []
            if isinstance(req, list) and req:
                out.append({"type": "require_fields", "fields": req})

            for clause in rules.get("deny_if", []) or []:
                if not isinstance(clause, dict):
                    continue
                field = clause.get("field")
                if not field:
                    continue
                # legacy deny_if only supported equals; map to execution_mode deny if relevant
                if field == "execution_mode" and "equals" in clause:
                    out.append({"type": "deny_execution_modes", "modes": [clause.get("equals")], "reason": clause.get("reason")})
                else:
                    out.append({"type": "deny_if", **clause})

            mb = rules.get("max_bytes_field")
            if isinstance(mb, dict) and mb.get("field") == "payload_bytes_in" and isinstance(mb.get("max"), int):
                out.append({"type": "max_payload_bytes", "event": "pre_exec", "max": mb.get("max"), "reason": mb.get("reason")})

            # If legacy dict had nothing else, allow by default
            if not out:
                out.append({"type": "allow_all"})
            return out

        return [{"type": "allow_all"}]

    def evaluate(self, tenant_id: str, policy_profile_id: str, gate: str, ctx: Dict[str, Any]) -> PolicyDecision:
        profile = self.load_profile(tenant_id, policy_profile_id)
        rules = self._normalize_rules(profile.get("rules"))

        def deny(reason: str, details: Optional[Dict[str, Any]] = None) -> PolicyDecision:
            return PolicyDecision(gate=gate, allow=False, reason=reason, policy_profile_id=profile["id"], details=details or {})

        def allow(reason: str = "allowed", details: Optional[Dict[str, Any]] = None) -> PolicyDecision:
            return PolicyDecision(gate=gate, allow=True, reason=reason, policy_profile_id=profile["id"], details=details or {})

        for rule in rules:
            rtype = str(rule.get("type") or "")
            rid = rule.get("id")

            if rtype == "require_fields":
                fields = rule.get("fields") or []
                if not isinstance(fields, list):
                    continue
                missing = [f for f in fields if ctx.get(f) in (None, "", [], {})]
                if missing:
                    return deny(f"missing required fields: {missing}", {"rule_id": rid, "missing": missing})

            elif rtype == "allow_execution_modes":
                modes = rule.get("modes") or []
                if isinstance(modes, list) and modes:
                    em = ctx.get("execution_mode")
                    if em not in modes:
                        return deny(rule.get("reason") or f"execution_mode not allowed: {em}", {"rule_id": rid, "execution_mode": em, "allowed": modes})

            elif rtype == "deny_execution_modes":
                modes = rule.get("modes") or []
                if isinstance(modes, list) and modes:
                    em = ctx.get("execution_mode")
                    if em in modes:
                        return deny(rule.get("reason") or f"execution_mode denied: {em}", {"rule_id": rid, "execution_mode": em})

            elif rtype == "allow_graph_ids":
                gids = rule.get("graph_ids") or []
                if isinstance(gids, list) and gids:
                    gid = ctx.get("graph_id")
                    if gid not in gids:
                        return deny(rule.get("reason") or f"graph_id not allowed: {gid}", {"rule_id": rid, "graph_id": gid, "allowed": gids})

            elif rtype == "allow_model_classes":
                classes = rule.get("classes") or []
                # Enforced during model dispatch; at pre_exec we only validate requested_model_class if present.
                requested = ctx.get("requested_model_class") or ctx.get("model_class")
                if requested is not None and isinstance(classes, list) and classes:
                    if requested not in classes:
                        return deny(rule.get("reason") or f"model_class not allowed: {requested}", {"rule_id": rid, "model_class": requested, "allowed": classes})

            elif rtype == "allow_model_ids":
                mids = rule.get("model_ids") or []
                mid = ctx.get("model_id")
                if mid is not None and isinstance(mids, list) and mids:
                    if mid not in mids:
                        return deny(rule.get("reason") or f"model_id not allowed: {mid}", {"rule_id": rid, "model_id": mid, "allowed": mids})

            elif rtype == "allow_tools":
                tools = rule.get("tools") or []
                tname = ctx.get("tool_name")
                if tname is not None and isinstance(tools, list) and tools:
                    if tname not in tools:
                        return deny(rule.get("reason") or f"tool not allowed: {tname}", {"rule_id": rid, "tool_name": tname, "allowed": tools})

            elif rtype == "deny_tools":
                tools = rule.get("tools") or []
                tname = ctx.get("tool_name")
                if tname is not None and isinstance(tools, list) and tools:
                    if tname in tools:
                        return deny(rule.get("reason") or f"tool denied: {tname}", {"rule_id": rid, "tool_name": tname})

            elif rtype == "max_payload_bytes":
                # Compare only on matching gate/event
                event = rule.get("event") or "pre_exec"
                if str(event) != str(gate):
                    continue
                maxv = rule.get("max")
                if isinstance(maxv, int):
                    val = ctx.get("payload_bytes_in")
                    if isinstance(val, int) and val > maxv:
                        return deny(rule.get("reason") or "payload too large", {"rule_id": rid, "payload_bytes_in": val, "max": maxv})

            elif rtype == "deny_if":
                # Generic legacy support: field equals
                field = rule.get("field")
                if field and "equals" in rule and ctx.get(field) == rule.get("equals"):
                    return deny(rule.get("reason") or f"denied: {field} equals {rule.get('equals')}", {"rule_id": rid, "field": field, "equals": rule.get("equals")})

            elif rtype == "allow_all":
                return allow("allowed", {"rule_id": rid})

        return allow("allowed")


class PolicyGateEnforcer:
    def __init__(self, tenant_id: str, policy_profile_id: str, job_id: str, repo_root: str = "."):
        self.tenant_id = tenant_id
        self.job_id = str(job_id)
        self.policy_profile_id = policy_profile_id
        self.engine = PolicyEngine(repo_root=repo_root)
        self.ctx_mgr = ContextManager(tenant_id=tenant_id, job_id=self.job_id)

    def _append_decision(self, decision: PolicyDecision) -> None:
        ctx = self.ctx_mgr.load()
        ctx.setdefault("policy_decisions", [])
        ctx["policy_decisions"].append({
            "gate": decision.gate,
            "allow": decision.allow,
            "reason": decision.reason,
            "policy_profile_id": decision.policy_profile_id,
            "details": decision.details or {},
        })
        self.ctx_mgr.set(ctx)
        self.ctx_mgr.save()

    def enforce(self, gate: str, ctx: Dict[str, Any]) -> None:
        decision = self.engine.evaluate(self.tenant_id, self.policy_profile_id, gate, ctx)
        self._append_decision(decision)
        if not decision.allow:
            raise PolicyViolation(decision.reason)

    def pre_exec(self, context: Dict[str, Any], payload_bytes: int) -> None:
        context = dict(context or {})
        context["payload_bytes_in"] = int(payload_bytes)
        self.enforce("pre_exec", context)

    def pre_agent(self, agent_name: str, context: Dict[str, Any]) -> None:
        context = dict(context or {})
        context["agent_name"] = agent_name
        self.enforce("pre_agent", context)

    def post_agent(self, agent_name: str, context: Dict[str, Any]) -> None:
        context = dict(context or {})
        context["agent_name"] = agent_name
        self.enforce("post_agent", context)

    def pre_tool_call(self, context: Dict[str, Any], **call_meta: Any) -> None:
        ctx = dict(context or {})
        ctx.update(call_meta)
        self.enforce("pre_tool_call", ctx)

    def post_tool_call(self, context: Dict[str, Any], **call_meta: Any) -> None:
        ctx = dict(context or {})
        ctx.update(call_meta)
        self.enforce("post_tool_call", ctx)

    def post_exec(self, context: Dict[str, Any]) -> None:
        self.enforce("post_exec", dict(context or {}))
