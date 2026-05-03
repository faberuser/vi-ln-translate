# Vibe Coded Light Novel EN / JP → VI Translator

Translate English or Japanese Light Novel EPUB files into fluent Vietnamese using the **Gemini Flash** API.  
Just drop EPUBs into `data/input/`, edit `config.yaml`, and run `python main.py`.

---

## Features

| Feature                 | Details                                                                                                                                      |
| ----------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| **EN & JP source**      | Supports both English→VI and Japanese→VI translation, each with tailored prompt instructions                                                 |
| **Literary quality**    | Prompts engineered for "mượt mà / thoát ý" prose, not word-for-word output                                                                   |
| **Pronoun System**      | Relationship Matrix — each character pair has their own 1st/2nd-person pronouns                                                              |
| **Glossary**            | Consistent name/term translation via simple YAML files                                                                                       |
| **Style Reference**     | Feed a reference book to make the AI mimic its Vietnamese writing style                                                                      |
| **Auto-scan**           | Auto-generates draft glossary, relationship, and **metadata** (book title + chapter titles) files before translating (one API call per EPUB) |
| **Context window**      | Previously translated chapters fed back as context for coherent narrative                                                                    |
| **Batch mode**          | Multiple chapters per API request to save free-tier RPD quota                                                                                |
| **Checkpoint / resume** | Progress saved after every chapter/chunk — resume after any interruption                                                                     |
| **AI evaluation**       | Optional second-pass quality check — 0–100 score + issue list                                                                                |

---

## Installation

```bash
# 1. Clone / unzip the project
cd vi-ln-translate

# 2. Create a virtual environment
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS/Linux

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set your Gemini API key
cp .env.example .env
# edit .env and set:  GEMINI_API_KEY=your_key_here
```

Get a free key at <https://aistudio.google.com/app/apikey>.

---

## Quick Start

1. Drop your `.epub` file(s) into `data/input/`
2. Set `source_language` in `config.yaml` (`en` for English, `jp` for Japanese)
3. (Optional) Drop previously translated volumes into `data/prior/`
4. (Optional) Drop a reference book into `data/style_references/` to have the AI mimic its writing style
5. Run:

```bash
python main.py
```

6. (Optional) Edit `data/metadata/{stem}_metadata.yaml`, `data/glossaries/{stem}_glossary.yaml`, or `data/relationships/{stem}_relationships.yaml` (files are matched by book name)
7. Press enter to start translation

Translated files are written to `data/output/<name>.epub`.

> **Auto-scan**: on first run the translator scans each input EPUB and auto-generates draft metadata, glossary and relationship files in `data/metadata/`, `data/glossaries/` and `data/relationships/`. Review and edit them, then press Enter to continue.

---

## Configuration — `config.yaml`

All settings live in `config.yaml`. No command-line arguments needed.

```yaml
# ── API ───────────────────────────────────────────────────────────────────────
api_key: "" # blank = read GEMINI_API_KEY from .env
model: gemini-3-flash-preview

# ── Paths ─────────────────────────────────────────────────────────────────────
input_dir: data/input # source EPUBs go here
output_dir: data/output # translated EPUBs written here
glossaries_dir: data/glossaries # *.yaml / *.json  → merged Glossary
relationships_dir: data/relationships # *.yaml / *.json  → merged RelationshipMatrix
metadata_dir: data/metadata # *.yaml             → per-book title & chapter titles
prior_volumes_dir: data/prior # *.epub (sorted)  → prior-volume context seed
style_references_dir: data/style_references # *.epub / *.txt  → writing style to mimic

# ── Translation ───────────────────────────────────────────────────────────────
source_language: en # "en" for English→VI, "jp" for Japanese→VI
batch: true # send chapters in chunks (saves RPD quota)
batch_size: 3 # chapters per API request
max_tokens: 65536 # max output tokens per request
context_window: 5 # past translated chapters to include as context (2–5, or ~ for all)
resume: true # resume from checkpoint on next run after interruption

# Chapter range — restrict which chapters are translated
start_chapter: 0 # 0-based inclusive
end_chapter: ~ # null = translate all chapters

# ── Auto-scan ─────────────────────────────────────────────────────────────────
auto_scan: true # auto-generate draft glossary + relationships before translating

# ── Quality evaluation ────────────────────────────────────────────────────────
evaluate: false # second-pass AI evaluation (costs 1 extra RPD per chapter)
review_threshold: 75.0 # chapters scoring below this are flagged for human review

# ── Misc ──────────────────────────────────────────────────────────────────────
verbose: false # show DEBUG-level logs
illustration_chapter: false # # collect ALL illustrations into a single "Minh Hoạ" chapter
```

### Key settings to tune

| Setting           | Recommendation                                                                                   |
| ----------------- | ------------------------------------------------------------------------------------------------ |
| `source_language` | `en` for English source, `jp` for Japanese source                                                |
| `batch_size`      | Lower (2) if you hit token limits; raise (8) for short chapters                                  |
| `context_window`  | `2`–`5` for ongoing stories; `1`–`2` for standalone; `~` to use all prior chapters               |
| `auto_scan`       | Keep `true` — generates glossary, relationships, and metadata automatically before the first run |

> **Why gemini-3-flash-preview?** Flash models reduce thinking overhead, which is not beneficial in translation and may increase output token counts.

---

## Data Files

For metadata, glossary and relationship, Gemini provides an initial translation during the scan. Review the file, correct any mistakes, then press Enter to start translating.

### Book Metadata (`data/metadata/{stem}_metadata.yaml`)

> **Auto-generated**: auto-generated by `auto_scan` at the same time as the glossary and relationships. One file per input EPUB, named `{stem}_metadata.yaml`.

```yaml
book_title:
    source: "魔女と傭兵"
    target: "Ma Nữ và Lính Đánh Thuê" # ← edit this
chapters:
    - source: "一話　双刃の故"
      target: "Chương 1: Lưỡi Đôi" # ← edit if needed
    - source: "あとがき"
      target: "Lời kết"
```

- **`book_title.target`** — used as the EPUB title (`dc:title`) of the translated output.
- **`chapters[].target`** — used as the chapter title in the translated output; overrides whatever Gemini produces during the main translation.

### Glossary (`data/glossaries/{stem}_glossary.yaml`)

> **Auto-generated**: with `auto_scan: true` (default), the translator calls Gemini once before translating to produce a draft glossary file. Review and edit it, then press Enter to continue.
>
> You can also create the file manually.

```yaml
entries:
    - source: "Sword Saint"
      target: "Kiếm Thánh"
      context: "Danh hiệu"
      notes: ""
```

The file must be named `{epub-stem}_glossary.yaml` (e.g. `vol07_glossary.yaml`). Only the glossary matching the current input EPUB is loaded — entries are injected into every translation prompt for that book.

### Relationship Matrix (`data/relationships/{stem}_relationships.yaml`)

> **Auto-generated**: similarly auto-generated by `auto_scan`.

```yaml
relationships:
    - char_a: "Arata"
      char_b: "Yuki"
      a_calls_self: "anh"
      a_calls_b: "em"
      context: "Lãng mạn"
      notes: ""
```

The file must be named `{epub-stem}_relationships.yaml`. Only the relationship file matching the current input EPUB is loaded. Tells the model exactly which Vietnamese pronouns each character uses for themselves and others.

### Prior Volumes (`data/prior/*.epub`)

Place previously translated volumes here (sorted by filename). The last `context_window` chapters of the latest volume are seeded as context when translating the next volume.

```
data/prior/
├── vol01_vi.epub
├── vol02_vi.epub
└── vol03_vi.epub  ← last N chapters seeded when translating vol04
```

### Style References (`data/style_references/*.epub` or `*.txt`)

Drop a book with excellent Vietnamese writing here to have the AI mimic its style.

**How it works:**

1. On first run, `BookStyleAnalyzer` samples 5 chapters from the reference book and calls Gemini to extract a detailed style profile: tone, sentence structure, vocabulary, pacing, distinctive features, and a concrete translation guide.
2. The profile is cached as `<stem>.style.yaml` in the same folder — **no extra API call on subsequent runs**.
3. The style guide is injected into every translation prompt.

```
data/style_references/
├── my-reference.epub       ← you put this here
└── my-reference.style.yaml ← auto-generated cache (editable)
```

> **Tip**: Use a Vietnamese-language EPUB/TXT for the best results — the AI learns from actual Vietnamese prose. You can open `<stem>.style.yaml` and edit any field manually, or delete it to force re-analysis. It is recommended to use the same genre as the translating book.

---

## Checkpoint / Resume

Translation progress is saved to `<output>.checkpoint.json` after every chapter (or batch chunk). If a run is interrupted for any reason (rate limit, Ctrl-C, crash), simply re-run `python main.py` — completed chapters are skipped automatically.

The checkpoint file is deleted when a volume finishes successfully.

To restart from scratch: delete the `data/output/*.checkpoint.json` file manually (or set `resume: false` in `config.yaml`).

---

## Translation Pipeline

```
data/input/*.epub
 └─► (auto_scan) Scan chapters → generate draft metadata + glossary + relationships
      └─► Load style reference profiles from data/style_references/
           └─► Extract chapters (ebooklib + BeautifulSoup)
                └─► Load checkpoint (skip already-translated chapters)
                     └─► For each batch chunk:
                          ├─ Build context (last N translated chapters + prior-volume seed)
                          ├─ Apply Glossary + Pronoun Matrix + Style Guide → prompt
                          ├─ [Gemini] Translate (EN→VI or JP→VI)
                          │       → ###CHAPTER[N]### / ###TITLE### / ###CONTENT###
                          ├─ Save checkpoint
                          └─ (optional) [Gemini] Evaluate → score / feedback / issues
 └─► Write translated EPUB to data/output/
 └─► Delete checkpoint
```

---

## Free-Tier API Limits

The default config is tuned for Gemini's free tier (20 RPD, 5 RPM):

| Setting           | Default | Why                                                  |
| ----------------- | ------- | ---------------------------------------------------- |
| `batch: true`     | on      | groups 3 chapters → 1 request instead of 3           |
| `batch_size: 3`   | 3       | balance between request count and output token limit |
| `evaluate: false` | off     | evaluation doubles RPD usage                         |
| `resume: true`    | on      | safe to stop/start                                   |

With 18 chapters and `batch_size: 3` you use 6 RPD instead of 18.
