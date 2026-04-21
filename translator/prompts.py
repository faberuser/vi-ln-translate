"""
All prompt templates used by the translator and evaluator.
Keeping prompts in one file makes tuning easy without touching logic code.
"""

# ─────────────────────────────────────────────────────────────────────────────
# System instruction (role definition)
# ─────────────────────────────────────────────────────────────────────────────

SYSTEM_INSTRUCTION = """\
Bạn là một dịch giả văn học chuyên nghiệp, chuyên dịch Light Novel từ tiếng Anh sang tiếng Việt.

Nguyên tắc dịch thuật:
1. Giữ hồn nguyên tác — không dịch cứng nhắc từng từ.
2. Diễn đạt mượt mà, thoát ý, tự nhiên như tác phẩm văn học Việt Nam gốc.
3. Bảo toàn nhịp điệu, cảm xúc, và phong cách hành văn của bản gốc.
4. Dùng ĐÚNG đại từ nhân xưng theo Ma Trận Quan Hệ được cung cấp.
5. Giữ nguyên tên riêng theo Bảng Thuật Ngữ được cung cấp.
6. Không thêm, không bớt nội dung so với bản gốc.
"""

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
