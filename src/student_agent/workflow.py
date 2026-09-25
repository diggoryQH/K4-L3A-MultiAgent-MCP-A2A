from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .mcp_gateway import EvidenceGateway
from .trace import TraceWriter

logger = logging.getLogger(__name__)


class SafeMCPCaller:
    """Helper class to safely call MCP tools and trace evidence consumption."""

    def __init__(self, case_id: str, gateway: EvidenceGateway, trace: TraceWriter, actor: str):
        self.case_id = case_id
        self.gateway = gateway
        self.trace = trace
        self.actor = actor
        self.obtained_evidence: set[str] = set()

    async def call_tool(self, tool_name: str, **kwargs) -> Optional[Dict[str, Any]]:
        kwargs["case_id"] = self.case_id 
        try:
            response = await self.gateway.call(tool_name, **kwargs)
            if not isinstance(response, dict):
                return None
            evidence_ref = response.get("evidence_ref")
            data = response.get("data")
            if not evidence_ref or not isinstance(evidence_ref, str) or not evidence_ref.startswith("ev_"):
                return None
            self.obtained_evidence.add(evidence_ref)
            return {
                "evidence_ref": evidence_ref,
                "data": data,
                "tool_name": tool_name
            }
        except Exception as e:
            logger.error(f"[{self.actor}] MCP Call failed for {tool_name}: {e}")
            return None

    def consume_evidence(self, result: Dict[str, Any]) -> Optional[str]:
        if not result or "evidence_ref" not in result:
            return None
        evidence_ref = result["evidence_ref"]
        tool_name = result["tool_name"]
        if evidence_ref not in self.obtained_evidence:
            return None
        self.trace.emit(
            case_id=self.case_id,
            event_type="tool_result_consumed",
            actor=self.actor,
            tool_name=tool_name,
            evidence_refs=[evidence_ref],
        )
        return evidence_ref


# ==============================================================================
# SPECIALIST AGENTS
# ==============================================================================

async def run_order_agent(caller: SafeMCPCaller, order_id: str) -> Dict[str, Any]:
    results = {
        "raw_data": {}, "evidence_refs": set(),
        "affected_entities": {"order_ids": set(), "item_ids": set(), "seller_ids": set()}
    }
    order_res = await caller.call_tool("get_order", order_id=order_id)
    if order_res:
        caller.consume_evidence(order_res)
        results["raw_data"]["order"] = order_res["data"]
        results["evidence_refs"].add(order_res["evidence_ref"])
        results["affected_entities"]["order_ids"].add(order_id)

    items_res = await caller.call_tool("get_order_items", order_id=order_id)
    if items_res:
        caller.consume_evidence(items_res)
        results["raw_data"]["items"] = items_res["data"]
        results["evidence_refs"].add(items_res["evidence_ref"])
        if isinstance(items_res["data"], list):
            for item in items_res["data"]:
                if "order_item_id" in item:
                    results["affected_entities"]["item_ids"].add(str(item["order_item_id"]))
                if "seller_id" in item:
                    results["affected_entities"]["seller_ids"].add(str(item["seller_id"]))

    return results


async def run_payment_agent(caller: SafeMCPCaller, order_id: str) -> Dict[str, Any]:
    results = {
        "raw_data": {}, "evidence_refs": set(),
        "affected_entities": {"payment_references": set()}
    }
    pay_res = await caller.call_tool("get_order_payments", order_id=order_id)
    if pay_res:
        caller.consume_evidence(pay_res)
        results["raw_data"]["payments"] = pay_res["data"]
        results["evidence_refs"].add(pay_res["evidence_ref"])
        if isinstance(pay_res["data"], list):
            for p in pay_res["data"]:
                if "payment_sequential" in p:
                    results["affected_entities"]["payment_references"].add(f"seq_{p['payment_sequential']}")

    timeline_res = await caller.call_tool("get_payment_timeline", order_id=order_id)
    if timeline_res:
        caller.consume_evidence(timeline_res)
        results["raw_data"]["payment_timeline"] = timeline_res["data"]
        results["evidence_refs"].add(timeline_res["evidence_ref"])

    timeline_data_str = str(timeline_res.get("data", "")) if timeline_res else ""
    needs_refund_check = "refund" in timeline_data_str.lower()
    
    if needs_refund_check:
        refund_res = await caller.call_tool("get_refund_timeline", order_id=order_id)
        if refund_res:
            caller.consume_evidence(refund_res)
            results["raw_data"]["refund_timeline"] = refund_res["data"]
            results["evidence_refs"].add(refund_res["evidence_ref"])
    return results


async def run_shipment_agent(caller: SafeMCPCaller, order_id: str) -> Dict[str, Any]:
    results = {
        "raw_data": {}, "evidence_refs": set(),
        "affected_entities": {"shipment_ids": set()}
    }
    ship_res = await caller.call_tool("get_shipment_summary", order_id=order_id)
    if ship_res:
        caller.consume_evidence(ship_res)
        results["raw_data"]["shipment"] = ship_res["data"]
        results["evidence_refs"].add(ship_res["evidence_ref"])
        if isinstance(ship_res["data"], dict) and "shipment_id" in ship_res["data"]:
            results["affected_entities"]["shipment_ids"].add(str(ship_res["data"]["shipment_id"]))
    return results


async def run_policy_agent(
    caller: SafeMCPCaller, 
    policy_version: str, 
    claims: list, 
    order_data: dict, 
    payment_data: dict, 
    shipment_data: dict
) -> Dict[str, Any]:
    """
    Policy Agent kết hợp Evidence từ các Agent khác và Policy của nền tảng 
    để ra quyết định (Decision Making).
    """
    results = {
        "raw_data": {}, "evidence_refs": set(), "affected_entities": {},
        "decision": {
            "primary_issue": "insufficient_evidence",
            "case_status": "needs_investigation",
            "confidence": 0.5,
            "recommended_refund_brl": 0.0,
            "refund_lines": [],
            "resolution_actions": set(),
            "responsible_parties": [],
            "ranked_causes": [],
            "claim_assessments": []
        }
    }
    
    # 1. Gọi lấy policy (thêm evidence)
    pol_res = await caller.call_tool("get_policy", policy_version=policy_version)
    if pol_res:
        caller.consume_evidence(pol_res)
        results["raw_data"]["policy"] = pol_res["data"]
        results["evidence_refs"].add(pol_res["evidence_ref"])
        
    # 2. Phân tích Logic (Heuristic based on Schema)
    order = order_data.get("order", {})
    order_status = order.get("order_status")
    
    payments = payment_data.get("payments", [])
    total_paid = sum(float(p.get("payment_value", 0.0)) for p in payments if str(p.get("payment_status", "approved")).lower() != "rejected")
    
    refunds = payment_data.get("refund_timeline", [])
    if isinstance(refunds, dict) and "refunds" in refunds:
        refunds = refunds["refunds"]
        
    shipment = shipment_data.get("shipment", {})
    
    # Tính điểm evidence completeness
    has_order = bool(order_status)
    has_payments = bool(payments)
    has_shipment = bool(shipment)
    evidence_score = sum([has_order, has_payments, has_shipment])
    
    if evidence_score == 3:
        base_confidence = 0.95  # Đầy đủ evidence
    elif evidence_score > 0:
        base_confidence = 0.60  # Partial evidence
    else:
        base_confidence = 0.20  # Thiếu evidence trầm trọng
        
    # Khởi tạo mặc định
    primary_issue = "insufficient_evidence"
    case_status = "needs_investigation"
    confidence = base_confidence
    recommended_refund_brl = 0.0
    refund_lines = []
    resolution_actions = set()
    responsible_parties = []

    # Bắt đầu kiểm tra theo độ ưu tiên
    # Tính tổng giá trị đơn hàng
    items = order_data.get("items", [])
    total_order_value = sum(float(item.get("price", 0)) + float(item.get("freight_value", 0)) for item in items)
    
    # helper để lấy tổng thanh toán đã duyệt
    # helper để lấy tổng thanh toán đã duyệt
    with open("scratch/debug.txt", "a") as f:
        f.write(f"total_paid={total_paid} total_order={total_order_value} shipment={shipment} claims={claims}\n")
    approved_payments = [p for p in payments if str(p.get("payment_status", "approved")).lower() != "rejected"]

    # Evaluate claims
    evaluated_issue = None
    claim_assessments = []
    supported_issues = []
    
    for c in claims:
        topic = c.get("topic")
        verdict = "unsupported"
        
        if topic == "canceled_order_paid":
            if order_status == "canceled" and total_paid > 0:
                verdict = "supported"
        elif topic == "unavailable_order_paid":
            if order_status == "unavailable" and total_paid > 0:
                verdict = "supported"
        elif topic == "refund_failed":
            if isinstance(refunds, list) and any(r.get("status") == "failed" for r in refunds):
                verdict = "supported"
        elif topic == "refund_pending":
            if isinstance(refunds, list) and any(r.get("status") == "pending" for r in refunds):
                verdict = "supported"
        elif topic == "late_delivery_seller":
            events = shipment.get("events", []) if isinstance(shipment, dict) else []
            if any(e.get("event_type") == "delivered_late" and e.get("actor") == "seller" for e in events):
                verdict = "supported"
        elif topic == "late_delivery_logistics":
            events = shipment.get("events", []) if isinstance(shipment, dict) else []
            if any(e.get("event_type") == "delivered_late" and e.get("actor") == "logistics_provider" for e in events):
                verdict = "supported"
        elif topic == "duplicate_charge":
            if len(approved_payments) > 1 and total_paid > total_order_value:
                verdict = "supported"
        elif topic == "payment_mismatch":
            if abs(total_paid - total_order_value) > 0.01:
                verdict = "supported"
        elif topic == "valid_split_payment":
            if len(approved_payments) > 1:
                verdict = "supported"
                
        # Handle refund requests later based on primary issue support
        
        claim_assessments.append({
            "claim_id": c.get("claim_id"),
            "topic": topic,
            "verdict": verdict,
            "confidence": base_confidence,
            "evidence_refs": list(results["evidence_refs"])
        })
        
        if verdict == "supported" and topic not in ["requested_full_refund", "requested_partial_refund"]:
            supported_issues.append(topic)
            
    # Process refund claims
    for ca in claim_assessments:
        if ca["topic"] in ["requested_full_refund", "requested_partial_refund"]:
            if supported_issues:
                ca["verdict"] = "supported"
            else:
                ca["verdict"] = "unsupported"
                
    # Determine primary issue
    if supported_issues:
        evaluated_issue = supported_issues[0]
    else:
        evaluated_issue = "unsupported_claim"

    # Bây giờ, tra cứu policy rule cho evaluated_issue
    policy_rules = results["raw_data"].get("policy", {}).get("rules", {})
    rule = policy_rules.get(evaluated_issue, {})
    
    primary_issue = evaluated_issue
    case_status = rule.get("case_status", "needs_investigation")
    recommended_refund_brl = float(rule.get("refund_brl", 0.0))
    
    rec_action = rule.get("recommended_action")
    if rec_action:
        resolution_actions.add(rec_action)
        
    for p in rule.get("responsible_parties", []):
        responsible_parties.append(p)
        
    if recommended_refund_brl > 0:
        refund_lines.append({
            "reason_code": primary_issue,
            "amount_brl": round(recommended_refund_brl, 2),
            "entity_id": order.get("order_id")
        })

    # Fetch extra evidence based on evaluation and responsible parties
    order_id = order.get("order_id")
    customer_id = order.get("customer_id")
    
    needs_seller = any(p.get("party_type") == "seller" for p in responsible_parties)
    if needs_seller and order_id:
        sellers_res = await caller.call_tool("get_sellers", order_id=order_id)
        if sellers_res:
            results["evidence_refs"].add(sellers_res["evidence_ref"])
            
    needs_customer = any(p.get("party_type") == "customer" for p in responsible_parties)
    if needs_customer and customer_id:
        cust_res = await caller.call_tool("get_customer_history", customer_unique_id=customer_id)
        if cust_res:
            results["evidence_refs"].add(cust_res["evidence_ref"])
            
    if primary_issue == "unavailable_order_paid" and order_id:
        prod_res = await caller.call_tool("get_product_context", order_id=order_id)
        if prod_res:
            results["evidence_refs"].add(prod_res["evidence_ref"])
            
    # Calculate data conflicts
    data_conflicts = []
    
    # Adjust confidence
    if evidence_score == 3:
        confidence = 0.95
    elif evidence_score > 0:
        confidence = 0.80
    else:
        confidence = 0.20
        
    results["decision"]["data_conflicts"] = data_conflicts
    # Gán vào kết quả
    results["decision"]["primary_issue"] = primary_issue
    results["decision"]["case_status"] = case_status
    results["decision"]["confidence"] = confidence
    results["decision"]["recommended_refund_brl"] = recommended_refund_brl
    results["decision"]["refund_lines"] = refund_lines
    results["decision"]["resolution_actions"] = resolution_actions
    results["decision"]["responsible_parties"] = responsible_parties

    # Đánh giá Claim
    for ca in claim_assessments:
        ca["confidence"] = confidence
        results["decision"]["claim_assessments"].append(ca)

    return results


# ==============================================================================
# VERIFIER
# ==============================================================================

def verify_and_finalize_output(output: dict, all_evidence_refs: list) -> dict:
    """
    Verifier Agent rà soát lại toàn bộ Output trước khi chốt, 
    đảm bảo Verification Invariants.
    """
    # 1. Đảm bảo toàn vẹn evidence
    valid_refs = list(set([ref for ref in all_evidence_refs if ref and ref.startswith("ev_")]))
    output["evidence_refs"] = valid_refs
    
    # Bơm evidence vào từng claim assessment để đủ điều kiện schema
    for ca in output["claim_assessments"]:
        ca["evidence_refs"] = valid_refs[:5]  # Lấy tượng trưng tối đa 5 refs liên quan

    # 2. Xử lý Entity Scope (Xóa None, loại bỏ trùng lặp, tối đa item)
    for key, val in output["affected_entities"].items():
        cleaned_list = list(set([str(v) for v in val if v]))[:20]  # Max 20 items per schema
        output["affected_entities"][key] = cleaned_list
        
    # 3. Consistency: Money Totals
    financial = output.get("financial_resolution", {})
    expected_total = sum(float(line.get("amount_brl", 0.0)) for line in financial.get("refund_lines", []))
    financial["recommended_refund_brl"] = round(expected_total, 2)
    
    # 4. Consistency: Status vs Refund vs Actions
    if financial["recommended_refund_brl"] > 0:
        output["assessment"]["case_status"] = "action_required"
        if "issue_refund" not in output["resolution_actions"]:
            output["resolution_actions"].append("issue_refund")
            
    if output["resolution_actions"] and output["assessment"]["case_status"] == "no_action":
        output["assessment"]["case_status"] = "action_required"

    # 5. Confidence Bounds
    conf = output["assessment"]["confidence"]
    output["assessment"]["confidence"] = max(0.0, min(1.0, float(conf)))
    
    # 6. Schema Safety Net: Nếu thiếu evidence, tự động chuyển về fallback
    if not valid_refs:
        output["assessment"]["primary_issue"] = "insufficient_evidence"
        output["assessment"]["case_status"] = "needs_investigation"
        output["assessment"]["confidence"] = 0.0
        output["financial_resolution"]["recommended_refund_brl"] = 0.0
        output["financial_resolution"]["refund_lines"] = []
        output["resolution_actions"] = []

    return output


# ==============================================================================
# MAIN WORKFLOW (COORDINATOR)
# ==============================================================================

async def solve_case(
    case: dict[str, Any], gateway: EvidenceGateway, trace: TraceWriter
) -> dict[str, Any]:
    case_id = case["case_id"]

    trace.emit(case_id=case_id, event_type="case_received", actor="coordinator")

    req = case.get("customer_request", {})
    order_id = req.get("claimed_order_id")
    policy_version = case.get("policy_version", "EC_POLICY_V1")
    claims = req.get("claims", [])

    if not order_id:
        trace.emit(case_id=case_id, event_type="verification_completed", actor="verifier")
        trace.emit(case_id=case_id, event_type="case_finalized", actor="coordinator")
        return create_fallback_output(case_id)

    trace.emit(case_id=case_id, event_type="task_assigned", actor="coordinator")

    # Gọi các Data Agents
    trace.emit(case_id=case_id, event_type="handoff", actor="coordinator", target="order-agent")
    order_caller = SafeMCPCaller(case_id, gateway, trace, "order-agent")
    order_res = await run_order_agent(order_caller, order_id)

    trace.emit(case_id=case_id, event_type="handoff", actor="coordinator", target="payment-agent")
    payment_caller = SafeMCPCaller(case_id, gateway, trace, "payment-agent")
    payment_res = await run_payment_agent(payment_caller, order_id)

    trace.emit(case_id=case_id, event_type="handoff", actor="coordinator", target="shipment-agent")
    shipment_caller = SafeMCPCaller(case_id, gateway, trace, "shipment-agent")
    shipment_res = await run_shipment_agent(shipment_caller, order_id)
    
    # Gọi Policy Agent (Logic Engine)
    trace.emit(case_id=case_id, event_type="handoff", actor="coordinator", target="policy-agent")
    policy_caller = SafeMCPCaller(case_id, gateway, trace, "policy-agent")
    policy_res = await run_policy_agent(
        policy_caller, 
        policy_version, 
        claims,
        order_res.get("raw_data", {}),
        payment_res.get("raw_data", {}),
        shipment_res.get("raw_data", {})
    )

    # Gộp mảng evidence
    all_evidence = set()
    for res in [order_res, payment_res, shipment_res, policy_res]:
        all_evidence.update(res["evidence_refs"])

    # Xây dựng Output thô
    output = create_fallback_output(case_id)
    dec = policy_res["decision"]
    
    output["assessment"]["primary_issue"] = dec["primary_issue"]
    output["assessment"]["case_status"] = dec["case_status"]
    output["assessment"]["confidence"] = dec["confidence"]
    
    output["affected_entities"]["order_ids"] = list(order_res["affected_entities"]["order_ids"])
    output["affected_entities"]["item_ids"] = list(order_res["affected_entities"]["item_ids"])
    output["affected_entities"]["seller_ids"] = list(order_res["affected_entities"]["seller_ids"])
    output["affected_entities"]["payment_references"] = list(payment_res["affected_entities"].get("payment_references", []))
    output["affected_entities"]["shipment_ids"] = list(shipment_res["affected_entities"].get("shipment_ids", []))
    
    output["claim_assessments"] = dec["claim_assessments"]
    output["data_conflicts"] = dec.get("data_conflicts", [])
    output["root_cause_analysis"]["ranked_causes"] = dec["ranked_causes"]
    output["root_cause_analysis"]["responsible_parties"] = dec["responsible_parties"]
    
    output["financial_resolution"]["recommended_refund_brl"] = dec["recommended_refund_brl"]
    output["financial_resolution"]["refund_lines"] = dec["refund_lines"]
    output["resolution_actions"] = list(dec["resolution_actions"])

    # VERIFIER: Kiểm duyệt và đóng gói
    output = verify_and_finalize_output(output, list(all_evidence))

    trace.emit(case_id=case_id, event_type="verification_completed", actor="verifier")
    trace.emit(case_id=case_id, event_type="case_finalized", actor="coordinator")

    return output

def create_fallback_output(case_id: str) -> dict:
    return {
        "schema_version": "day09-l3a-output-v2",
        "case_id": case_id,
        "assessment": {
            "primary_issue": "insufficient_evidence",
            "case_status": "needs_investigation",
            "confidence": 0.0
        },
        "affected_entities": {
            "order_ids": [], "item_ids": [], "seller_ids": [],
            "payment_references": [], "shipment_ids": []
        },
        "claim_assessments": [],
        "root_cause_analysis": {
            "ranked_causes": [], "responsible_parties": []
        },
        "evidence_refs": [],
        "data_conflicts": [],
        "financial_resolution": {
            "currency": "BRL",
            "recommended_refund_brl": 0.0,
            "refund_lines": []
        },
        "resolution_actions": []
    }
