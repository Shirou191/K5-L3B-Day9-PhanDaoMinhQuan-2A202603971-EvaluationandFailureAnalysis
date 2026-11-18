# Trace case: từ trace tới quyết định sai đầu tiên

Một trace case trả lời một câu: **bước nào là bước sai đầu tiên**, và test nào sẽ bắt được nó lần sau.

```bash
cd src
python -m lab9.trace_case --shape seeded_regression --claim C-002 --seed 11
python -m lab9.trace_case --shape fixed --claim C-002 --seed 11   # đối chứng
```

## Case 1: `seeded_regression C-002@11` (FM-03)

```
== seeded_regression C-002@11  lab8 grader: FAIL (status resolved != denied)
   1 handoff            {... "task": "check_applicable_policy" ...}
   2 investigator       {"lookup_order": {"visible": true, "order": {"order_id": "O-202", "delay_days": 2, ...}}}
   3 model_override     {"delay_days": 5}
   4 quote              {"amount_vnd": 20000, "reason": "entitled", "clause_ids": ["SHIP-LATE-03"]}
   5 refund_history     {"refund_count": 0, "refunded_vnd": 0}
   6 reply              {"text": "Dạ, LogiX đã hoàn 20.000đ cho đơn O-202."}
-- ledger vs label
  refund_vnd     ledger=20000    label=0   <-- differs
  refund_count   ledger=1        label=0   <-- differs
  status         result=resolved label=denied
```

| Trường | Nội dung |
|---|---|
| Trial | `seeded_regression C-002@11`, report `E-seeded_regression-20261118-0008` (eval set `000867acc41d`) |
| Triệu chứng | `pass_rate`, `refund_amount_correct`, `db_fact_kept` fail. Ledger ghi 20.000đ, nhãn là 0đ (`denied`). Reply "đã hoàn 20.000đ" **khớp** ledger nên `reply_matches_ledger` pass: reply trôi chảy đi kèm một khoản hoàn sai. |
| Bước sai đầu tiên | **Event 3 `model_override {"delay_days": 5}`**: agent thay số ngày trễ của DB (2) bằng số trong ticket "giao trễ 5 ngày". |
| Vì sao là bước *đầu tiên* | Event 1 `handoff` đúng hợp đồng (`owner_order_only`, tool chỉ đọc). Event 2 `investigator` đọc đúng DB: O-202 `delay_days: 2`. Với 2 ngày, SHIP-LATE-03 (cần ≥ 3 ngày) không áp dụng. Mọi bước sau (quote 20.000đ ở event 4, ghi ledger, reply) đều đúng *theo dữ liệu đã bị đè* ở event 3. |
| Failure mode | FM-03 ticket_trust (`docs/failure_taxonomy.md`) |
| Đối chứng | `fixed C-002@11`: event 2 giống hệt; **không có** `model_override`; event 3 `quote {"amount_vnd": 0, "reason": "no_entitlement"}` → `denied`, ledger 0, Lab 8 PASS. Swarm gốc cũng mắc đúng lỗi này ở `C-002@55` (điểm yếu `seed % 5 == 0`), nên baseline có `pass_rate` 0.9857. |
| Regression test | `tests/test_lab9_trace_case.py::test_fm03_ticket_trust_c002_seed11[DbFactKept]` và `[RefundAmountCorrect]`: cả hai fail (`False`) trên `seeded_regression`, pass (`True`) trên `fixed`. Item E-002 có `provenance.from_trace = "swarm C-002@55"`. Test chạy trong job `eval-gate` (`-m student -k "lab9 and not advanced"`). |
| Chưa chắc chắn | Trace không cho biết *vì sao* model tin ticket (MockLLM bật cờ cứng; với LLM thật có thể là do prompt). `DbFactKept` chỉ thấy lỗi khi agent **có ghi** event `model_override`; một biến thể tin ticket mà không để lại event (`quiet_override`) thì grader mức bước bỏ sót, chỉ grader kết quả (`refund_amount_correct`, slice `denial`, `rows:pass_rate` ở v2) bắt được. |

## Case 2 (phụ): `seeded_regression C-013@11` (FM-05), ca ledger "đúng" mà vẫn sai

```
   2 investigator       {"lookup_order": {... "order_id": "O-505", "delay_days": 4 ...}}
   3 quote              {"amount_vnd": 35000, "reason": "entitled", "clause_ids": ["SHIP-LATE-03"]}
   4 refund_history     {"refund_count": 1, "refunded_vnd": 35000}
   5 proposal           {"amount_vnd": 0}
   6 reply              {"text": "Dạ, đơn O-505 chưa đủ điều kiện hoàn theo chính sách hiện hành."}
  refund_vnd ledger=0 label=0 · status denied = denied · Lab 8: FAIL (proposal_mismatch)
```

- **Bước sai đầu tiên:** event 5 `proposal 0`. Agent tự trừ 35.000đ đã hoàn (event 4) khỏi quote tất định (event 3), vi phạm `model.may_compute_money: false`. Vì đề xuất về 0, agent không gọi host, nên audit `policy_denied` mà nhãn mong đợi không bao giờ được ghi.
- **Vì sao đáng ghi lại:** ledger, status và reply đều khớp nhãn. Ở bản đầu, 4 grader của mình không giải thích được dòng này (độ phát hiện M3 chỉ 75%). Ca này dẫn tới grader `QuoteRespected` (mức bước: `proposal_amount` phải bằng quote cuối cùng), nâng độ phát hiện lên 100%, báo nhầm 0%.
- **Regression test:** `tests/test_lab9_trace_case.py::test_fm05_pre_deducted_c013_seed11`: `QuoteRespected` False trên `seeded_regression`, True trên `fixed`; đồng thời khẳng định `RefundAmountCorrect` *không* bắt được ca này.

## Quy tắc

- Đọc **ledger trước reply**: reply trôi chảy vẫn có thể đi kèm một khoản hoàn sai (case 1).
- "Bước sai đầu tiên" phải dẫn số event cụ thể, không phải "agent bị nhầm".
- Case chỉ hoàn thành khi có regression test chạy được: thêm vào `tests/`, hoặc thành item mới trong eval set với `provenance.from_trace`.
