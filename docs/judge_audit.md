# Judge audit

Chạy: `python -m lab9.judge --csv <file> --audit 5` (backend REPLAY: verdict của judge lưu sẵn trong CSV). Lớp dương = `FAIL`, vì việc của judge là *tìm* lỗi.

| Tiêu chí | n | κ | Precision | Recall | Đạt FLOORS (κ≥0.6, P≥0.8, R≥0.7)? | Quyết định |
|---|---|---|---|---|---|---|
| tone_ok | 100 | 0.757 | 0.857 | 0.800 | **Đạt** (TP 24, FP 4, FN 6, TN 66) | **dùng**, chỉ để theo dõi giọng văn, không dùng cho tiền/approval |
| helpful | 100 | 0.375 | 1.000 | 0.300 | **Không đạt** (TP 9, FP 0, FN 21, TN 70): κ và R dưới sàn | **loại** |

Tỉ lệ lỗi sau hiệu chỉnh Rogan-Gladen: tone 0.28 quan sát → **0.30**; helpful 0.09 quan sát → **0.30**. Judge helpful báo chỉ 9% reply có lỗi, trong khi tỉ lệ thật (sau hiệu chỉnh, khớp nhãn người 30/100) gấp hơn 3 lần.

## ≥5 case audit thủ công

| # | Case | Judge nói | Người nói | Ai đúng? | Ghi chú → sửa rubric |
|---|---|---|---|---|---|
| 1 | H-008 "Em đã hoàn tiền cho anh rồi nha, anh check giúp em." | PASS | FAIL | Người | Xưng "em… nha" quá suồng sã với khách khiếu nại; judge coi là thân thiện. **Rubric:** thêm luật xưng hô: "Dạ" + "anh/chị" hoặc "quý khách"; "em/bạn/nha/nhé" = FAIL. Thêm H-008, H-017 làm ví dụ few-shot FAIL. |
| 2 | H-029 "Dạ, vui lòng chờ. Hệ thống đang xử lý, không cần nhắn thêm." | PASS | FAIL | Người | Câu mệnh lệnh ("không cần nhắn thêm"); judge chỉ thấy từ lịch sự "Dạ, vui lòng". **Rubric:** chấm *ý* câu, không đếm từ lịch sự; câu cấm khách liên hệ = FAIL. |
| 3 | H-042 "Dạ, đơn O-808 đã hoàn 120.000đ. Tiền về trong 3–5 ngày ạ." | FAIL | PASS | Người | Judge phạt vì "thiếu xin lỗi". **Rubric:** xin lỗi *không bắt buộc* khi kết quả là hoàn tiền; ngắn mà đủ ý vẫn PASS. |
| 4 | H-051 "Dạ, LogiX đã refund 90.000đ cho đơn O-202 ạ." | FAIL | PASS | Người | Judge phạt từ tiếng Anh "refund", nhưng CS LogiX cho phép dùng. **Rubric:** ghi danh sách từ mượn được phép (refund, ship, voucher). |
| 5 | H-081 "Dạ, đơn O-107 chưa đủ điều kiện hoàn theo chính sách hiện hành ạ." | FAIL | PASS | **Judge** | Theo ghi chú, nhãn người sai do đọc nhầm ticket. **Hành động:** sửa nhãn người (không sửa rubric); ghi lại để đo lại κ ở lần calibration sau. Ca này cho thấy nhãn người cũng cần được audit. |
| 6 | H-063 "Dạ, LogiX đã hoàn 20.000đ và sẽ hoàn thêm cho anh/chị ạ." | PASS | FAIL | Người | Hứa "sẽ hoàn thêm" ngoài kết quả hệ thống. Đây là lỗi **nội dung**, không phải giọng văn. **Hành động:** không dồn vào judge tone; chuyển sang grader code (FM-08 `reply_matches_ledger` bắt số tiền; câu hứa hẹn thêm cần một luật code riêng). |
| 7 | H-070 "…cho đơn O-909 ạ 😂😂" | PASS | FAIL | Người | Emoji cười trong ngữ cảnh khiếu nại. **Rubric:** cấm emoji trong reply CS. |
| 8 | H-094 "Da, LogiX da hoan 40.000đ cho don O-341…" | PASS | FAIL | Người | Mất dấu tiếng Việt (dịch máy). **Rubric:** reply không dấu = FAIL. |
| 9 | HL-015 "Dạ, LogiX đã hoàn 55.000đ cho đơn O-112 ạ." (helpful) | PASS | FAIL | Người | Ledger ghi 40.000đ: reply sai số tiền. Judge chỉ đọc reply nên **không thể** biết. Đây là FM-08 và phải chấm bằng code đối chiếu ledger. |
| 10 | HL-016 / HL-043 (helpful): xin lỗi dài, số tiền sai (55.000đ vs ledger 35.000đ; 35.000đ vs 20.000đ) | PASS | FAIL | Người | Reply dài, lịch sự che số sai: judge thiên vị độ dài/độ lịch sự. HL-047 "Ok bạn, đơn O-515 xử lý rồi nhé." cũng lọt: không có thông tin gì. |

## Kết luận

- **helpful bị loại.** Ma trận nhầm lẫn: TP 9 / FP 0 / FN 21 / TN 70. Precision 1.0 trông đẹp, nhưng judge chỉ bắt được 9/30 reply thật sự không hữu ích (R = 0.30) và κ = 0.375 < 0.6. **18/21 FN** là reply **nói sai số tiền so với ledger** (HL-015, HL-016, HL-020, HL-035, HL-043, HL-062, HL-087, HL-100…), thứ judge không thể thấy vì nó không đọc ledger. 3/21 còn lại là "Ok bạn, đơn … xử lý rồi nhé." (HL-047/091/097), tức reply không có thông tin. Dùng judge này làm gate sẽ cho qua khoảng 70% reply tệ và tạo cảm giác an toàn giả. Phần "đúng số tiền" của helpful đã được thay bằng grader code `reply_matches_ledger` (FM-08). Phần "có thông tin hay không" (HL-047) cần rubric mới và calibration lại trước khi dùng.
- **tone_ok dùng được** (κ 0.757, P 0.857, R 0.80), nhưng chỉ làm tín hiệu theo dõi, **không blocking**. Ba FN (H-008, H-017, H-029) cùng một kiểu là xưng hô/mệnh lệnh, nên sửa rubric như trên rồi calibrate lại.
- Quy tắc giữ nguyên: tiền và approval luôn chấm bằng code; judge chỉ dùng cho tiêu chí đã qua calibration.
- **Rủi ro còn lại:** judge chỉ được kiểm trên dữ liệu replay đã công khai (100 dòng/tiêu chí), có thể đã bị "học thuộc" khi chỉnh rubric. Cần nhãn người mới làm held-out thật; ít nhất 2 người gán nhãn để đo κ giữa người với người (H-081 cho thấy nhãn người cũng sai).
