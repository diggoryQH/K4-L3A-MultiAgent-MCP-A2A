# L3A Architecture Record

Team phải cập nhật tài liệu này cùng source. Mục tiêu là mô tả quyết định có thể kiểm chứng, không ghi prompt bí mật hoặc chain-of-thought.

## 1. System overview

Luồng xử lý từ input đến output qua các Specialist Agents, được điều phối bởi Coordinator.

```text
Input (case.json) → Coordinator → Order Agent
                                  Payment Agent
                                  Shipment Agent
                                  Policy Agent
                                        │
                                        ▼
                                     Verifier
                                        │
                                        ▼
                                Output (outputs/<case_id>.json)
                                        │
MCP Evidence Gateway ───────────────────┴── Trace (traces/trace.jsonl)
```

## 2. Agent ownership

| Actor | Input | Trách nhiệm | Output/handoff | Tool được phép gọi |
| --- | --- | --- | --- | --- |
| Coordinator | `case_id`, nội dung khiếu nại | Phân tích yêu cầu, phân phối công việc cho các agent, tổng hợp dữ liệu. Emit `case_received`, `task_assigned`, `case_finalized`. | Handoff công việc tới Specialist, handoff dữ liệu tới Verifier. | Không |
| Order/Item Agent | `case_id`, `order_id` | Lấy chi tiết đơn hàng, mặt hàng, người bán. Xác định `affected_entities` (order, item, seller). | Trạng thái đơn hàng, ID liên quan, `evidence_refs`. Handoff về Coordinator. | `get_order`, `get_order_items`, `get_sellers`, `get_product_context` |
| Payment Agent | `case_id`, `order_id`, `payment_ref` | Đối chiếu thanh toán, hoàn tiền. Tính `financial_resolution`. | Chi tiết thanh toán, `evidence_refs`. Handoff về Coordinator. | `get_order_payments`, `get_payment_timeline`, `get_refund_timeline` |
| Shipment Agent | `case_id`, `order_id` | Kiểm tra giao hàng, trễ hạn. Xác định nguyên nhân (seller vs logistics). | Trạng thái giao hàng, lỗi của ai, `evidence_refs`. Handoff về Coordinator. | `get_shipment_summary` |
| Policy Agent | Bối cảnh khiếu nại | Đối chiếu chính sách của nền tảng xem claim có hợp lệ không. | `resolution_actions`, `evidence_refs`. Handoff về Coordinator. | `get_policy` |
| Verifier | Dữ liệu tổng hợp | Rà soát `consistency`, tính `confidence`, sinh output đúng JSON schema. Đảm bảo toàn vẹn evidence. | Output JSON. Handoff lưu file. | Không |

## 3. A2A protocol

- **Message envelope**: Dùng `case_id` làm khóa tương quan (correlation id) trong toàn bộ payload trao đổi.
- **Handoff**: Các Specialist trả về một dictionary chuẩn hóa chứa `data` và mảng `evidence_refs`.
- **Trace**: Chỉ emit trace ở các mốc quan trọng (nhận case, giao task, tiêu thụ tool result, kiểm tra xong, hoàn thành case). Không trace các bước suy luận nội bộ.

## 4. Evidence lifecycle

- **Validation**: Mọi MCP response được lưu trữ và bóc tách `evidence_ref`.
- **Consumption**: Ngay khi dùng dữ liệu từ MCP để đưa ra kết luận, agent sẽ gọi `trace.emit(event_type="tool_result_consumed", evidence_refs=[...])`.
- **Output linkage**: Toàn bộ `evidence_refs` hợp lệ sẽ được map thẳng vào `claim_assessments` và mảng `evidence_refs` của output schema. Cấm tái sử dụng evidence giữa các case.

## 5. Failure policy

| Failure | Retry? | Fallback | Trace event/code |
| --- | --- | --- | --- |
| MCP timeout | Có (tối đa 3 lần) | Chờ exponential backoff. Nếu vẫn fail, ngưng case. | Không emit trace nếu rỗng. |
| Not found | Không | Ghi nhận entity không tồn tại, claim `unsupported`. | `tool_result_consumed` với evidence_ref (nếu API có trả về empty evidence). |
| Source conflict | Không | Ưu tiên dữ liệu hệ thống (MCP) hơn claim khách hàng. | Ghi nhận vào field `data_conflicts`. |
| Invalid specialist result | Không | Verifier bắt lỗi và reject logic, ghi log. | `verification_completed` với confidence thấp. |

## 6. Verification invariants

Trước khi xuất file JSON, Verifier sẽ kiểm tra:
1.  **Schema**: Đáp ứng 100% `day09-l3a-output-v2.schema.json`.
2.  **Entity scope**: Mọi ID trong `affected_entities` phải xuất phát từ MCP.
3.  **Claim linkage**: Các claim phải map 1-1 với `case.json` input.
4.  **Money totals**: `recommended_refund_brl` phải bằng tổng `amount_brl` của `refund_lines`.
5.  **Evidence ownership**: Không có `evidence_ref` nào tự bịa (hallucinated) hoặc sai format `ev_...`.

## 7. Reproducibility

- Lệnh chạy: `day09 run`
- Môi trường: Python 3.12.2, cài đặt qua `pip install -e ".[dev]"`.
- Không sử dụng token bí mật ngoài `COMPETITION_TEAM_API_KEY` (được cách ly trong `.env`).
