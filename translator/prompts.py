"""
All prompt templates used by the translator and evaluator.
Keeping prompts in one file makes tuning easy without touching logic code.
"""

# ─────────────────────────────────────────────────────────────────────────────
# System instructions (role definition) — one per source language
# ─────────────────────────────────────────────────────────────────────────────

SYSTEM_INSTRUCTION_EN = """\
Bạn là một dịch giả văn học chuyên nghiệp, chuyên dịch Light Novel từ tiếng Anh sang tiếng Việt.

Nguyên tắc dịch thuật:
1. Giữ hồn nguyên tác — không dịch cứng nhắc từng từ.
2. Diễn đạt mượt mà, thoát ý, tự nhiên như tác phẩm văn học Việt Nam gốc.
3. Bảo toàn nhịp điệu, cảm xúc, và phong cách hành văn của bản gốc.
4. Dùng ĐÚNG đại từ nhân xưng theo Ma Trận Quan Hệ được cung cấp.
5. Giữ nguyên tên riêng theo Bảng Thuật Ngữ được cung cấp.
6. Không thêm, không bớt nội dung so với bản gốc.
"""

SYSTEM_INSTRUCTION_JP = """\
Bạn là một dịch giả văn học chuyên nghiệp, chuyên dịch Light Novel từ tiếng Nhật sang tiếng Việt.

Nguyên tắc dịch thuật:
1. Giữ hồn nguyên tác — không dịch cứng nhắc từng từ.
2. Diễn đạt mượt mà, thoát ý, tự nhiên như tác phẩm văn học Việt Nam gốc.
3. Bảo toàn nhịp điệu, cảm xúc, và phong cách hành văn của bản gốc.
4. Dùng ĐÚNG đại từ nhân xưng theo Ma Trận Quan Hệ được cung cấp.
5. Giữ nguyên tên riêng theo Bảng Thuật Ngữ được cung cấp.
6. Không thêm, không bớt nội dung so với bản gốc.
7. Chú ý các đại từ nhân xưng tiếng Nhật (ore, boku, watashi, kimi, anata, v.v.) và chuyển thành đại từ tiếng Việt phù hợp theo Ma Trận Quan Hệ.
8. Onomatopoeia tiếng Nhật: dịch nghĩa tự nhiên nếu có thể, giữ nguyên phiên âm chỉ khi không có từ tương đương.
9. Các từ văn hóa đặc thù (senpai, kouhai, sensei, v.v.) giữ nguyên hoặc dịch theo Bảng Thuật Ngữ.
"""

# Legacy alias kept for any direct imports
SYSTEM_INSTRUCTION = SYSTEM_INSTRUCTION_EN


def get_system_instruction(source_language: str = "en") -> str:
    """Return the system instruction appropriate for the given source language."""
    if source_language.lower() in ("jp", "ja", "japanese"):
        return SYSTEM_INSTRUCTION_JP
    return SYSTEM_INSTRUCTION_EN

# ─────────────────────────────────────────────────────────────────────────────
# Translation prompt
# ─────────────────────────────────────────────────────────────────────────────

TRANSLATION_PROMPT_TEMPLATE = """\
{glossary_section}

{pronoun_section}

{context_section}

════════════════════════════════════════
CHƯƠNG CẦN DỊCH
════════════════════════════════════════
Tiêu đề: {chapter_title}

{chapter_content}

════════════════════════════════════════
YÊU CẦU ĐẦU RA
════════════════════════════════════════
Dịch toàn bộ chương trên sang tiếng Việt.
Trả lời CHÍNH XÁC theo định dạng dưới đây (không thêm bất kỳ văn bản nào ngoài định dạng):

###TITLE###
[Tiêu đề chương đã dịch]
###CONTENT###
[Toàn bộ nội dung chương đã dịch — giữ nguyên cấu trúc đoạn văn, xuống dòng giữa các đoạn]
"""

# ─────────────────────────────────────────────────────────────────────────────
# Batch translation prompt (entire volume in one request)
# ─────────────────────────────────────────────────────────────────────────────

BATCH_TRANSLATION_PROMPT_TEMPLATE = """\
{glossary_section}

{pronoun_section}

{context_section}

════════════════════════════════════════
DANH SÁCH CHƯƠNG CẦN DỊCH ({chapter_count} CHƯƠNG)
════════════════════════════════════════
{chapters_block}

════════════════════════════════════════
YÊU CẦU ĐẦU RA
════════════════════════════════════════
Dịch TOÀN BỘ {chapter_count} chương trên sang tiếng Việt theo đúng thứ tự.
Trả lời CHÍNH XÁC theo định dạng dưới đây cho TỪNG chương (không thêm bất kỳ văn bản nào ngoài định dạng):

###CHAPTER[1]###
###TITLE###
[Tiêu đề chương 1 đã dịch]
###CONTENT###
[Toàn bộ nội dung chương 1 đã dịch]
###CHAPTER[2]###
###TITLE###
[Tiêu đề chương 2 đã dịch]
###CONTENT###
[Toàn bộ nội dung chương 2 đã dịch]
... (tiếp tục cho tất cả {chapter_count} chương)
"""

# Template for one chapter entry inside the batch prompt
BATCH_CHAPTER_ENTRY = """\
---[ CHƯƠNG {index}: {title} ]---
{content}"""

# ─────────────────────────────────────────────────────────────────────────────
# Evaluation / QC prompt
# ─────────────────────────────────────────────────────────────────────────────

EVALUATION_PROMPT_TEMPLATE = """\
Bạn là biên tập viên văn học. Hãy đánh giá chất lượng bản dịch Light Novel dưới đây.

{glossary_section}

════════════════════════════════════════
VĂN BẢN GỐC (tiếng Anh)
════════════════════════════════════════
Tiêu đề: {source_title}

{source_content}

════════════════════════════════════════
BẢN DỊCH (tiếng Việt)
════════════════════════════════════════
Tiêu đề: {translated_title}

{translated_content}

════════════════════════════════════════
TIÊU CHÍ ĐÁNH GIÁ
════════════════════════════════════════
1. Độ chính xác tên nhân vật và thuật ngữ (theo Bảng Thuật Ngữ nếu có)
2. Không bỏ sót câu/đoạn văn
3. Đại từ nhân xưng nhất quán và đúng quan hệ nhân vật
4. Chất lượng văn phong — mượt mà, tự nhiên, thoát ý
5. Bảo toàn ý nghĩa và cảm xúc của bản gốc

════════════════════════════════════════
YÊU CẦU ĐẦU RA
════════════════════════════════════════
Trả lời CHÍNH XÁC theo định dạng (không thêm gì ngoài định dạng):

###SCORE###
[Điểm từ 0 đến 100]
###FEEDBACK###
[Nhận xét tổng quát ngắn gọn (2-4 câu)]
###ISSUES###
[Danh sách các lỗi cụ thể, mỗi lỗi một dòng bắt đầu bằng "- ". Nếu không có lỗi đáng kể, ghi: "- Không có lỗi đáng kể."]
"""

# ─────────────────────────────────────────────────────────────────────────────
# Book scanner prompts (auto-generate glossary & relationships before translation)
# ─────────────────────────────────────────────────────────────────────────────

SCAN_SYSTEM_INSTRUCTION = """\
Bạn là trợ lý phân tích văn bản chuyên nghiệp, giúp chuẩn bị tài liệu hỗ trợ dịch thuật Light Novel sang tiếng Việt.
Nhiệm vụ của bạn là đọc các đoạn trích từ Light Novel và trích xuất thuật ngữ, tên riêng, cùng quan hệ xưng hô giữa nhân vật.
Hãy trả lời ĐÚNG theo định dạng được yêu cầu — không thêm giải thích hay văn bản nào khác.
"""

SCAN_EXTRACTION_PROMPT_TEMPLATE = """\
Phân tích các đoạn trích Light Novel dưới đây (ngôn ngữ gốc: {source_language_name}).

{chapters_text}

════════════════════════════════════════
YÊU CẦU TRÍCH XUẤT
════════════════════════════════════════
Trả lời ĐÚNG theo 2 phần sau. Không thêm bất kỳ văn bản nào ngoài 2 phần này.

###GLOSSARY###
entries:
  - source: "[tên/thuật ngữ trong bản gốc]"
    target: "[bản dịch tiếng Việt đề xuất]"
    context: "[nhân vật | địa danh | kỹ năng/ma pháp | chức vị | vật phẩm | khác]"
    notes: "[ghi chú nếu cần, hoặc để trống]"

###RELATIONSHIPS###
relationships:
  - char_a: "[tên nhân vật A]"
    char_b: "[tên nhân vật B]"
    a_calls_self: "[đại từ A tự xưng khi nói với B, ví dụ: tôi / anh / ta / mình / tao]"
    a_calls_b: "[đại từ A gọi B, ví dụ: em / bạn / cậu / ngươi / mày]"
    context: "[mô tả quan hệ, ví dụ: Bạn bè / Anh-Em / Senpai-Kohai / Tình nhân / Chủ-Tớ]"
    notes: "[ghi chú nếu cần, hoặc để trống]"

Lưu ý quan trọng:
- Chỉ liệt kê những tên/thuật ngữ xuất hiện RÕ RÀNG trong văn bản.
- Với tên riêng không có nghĩa, giữ nguyên phiên âm trong target.
- Với quan hệ nhân vật, chỉ thêm những cặp mà bạn có đủ bằng chứng từ văn bản.
- Nếu một quan hệ chưa rõ, bỏ qua thay vì đoán mò.
- Output phải là YAML hợp lệ.
"""
