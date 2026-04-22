# Vibe Coded Light Novel EN → VI Translator

Translate English Light Novel EPUB files into fluent Vietnamese using the **Gemini Flash** API.  
Just drop EPUBs into `data/input/`, edit `config.yaml`, and run `python main.py`.

---

## Features

| Feature                  | Details                                                                         |
| ------------------------ | ------------------------------------------------------------------------------- |
| **Literary quality**     | Prompts engineered for "mượt mà / thoát ý" prose, not word-for-word output      |
| **Pronoun System**       | Relationship Matrix — each character pair has their own 1st/2nd-person pronouns |
| **Glossary**             | Consistent name/term translation via simple YAML files                          |
| **Context window**       | Previously translated chapters fed back as context for coherent narrative       |
| **Batch mode**           | Multiple chapters per API request to save free-tier RPD quota                   |
| **Checkpoint / resume**  | Progress saved after every chapter/chunk — resume after any interruption        |
| **AI evaluation**        | Optional second-pass quality check — 0–100 score + issue list                   |
| **EPUB chapter trimmer** | Dedicated script to strip unwanted chapters before or after translation         |
| **EPUB I/O**             | Reads & writes standard EPUB 2/3 files via `ebooklib`                           |

---

## Installation

```bash
# 1. Clone / unzip the project
cd en-to-vn-ln-translate

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
2. (Optional) Edit `config.yaml` if needed (see below)
3. (Optional) Edit `glossaries/*.yaml` or `relationships/*.yaml` if needed (see below)
4. (Optional) Drop previously VI translated volumes into `data/prior/` if needed (see below)
5. Run:

```bash
python main.py
```

Translated files are written to `data/output/<name>.epub`.

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
prior_volumes_dir: data/prior # *.epub (sorted)  → prior-volume context seed

# ── Translation ───────────────────────────────────────────────────────────────
batch: true # send chapters in chunks (saves RPD quota)
batch_size: 3 # chapters per API request
max_tokens: 65536 # max output tokens per request
context_window: 5 # past translated chapters to include as context (2–5, or ~ for all)
resume: true # resume from checkpoint on next run after interruption

# Chapter range — restrict which chapters are translated
start_chapter: 0 # 0-based inclusive
end_chapter: ~ # null = translate all chapters

# ── Quality evaluation ────────────────────────────────────────────────────────
evaluate: false # second-pass AI evaluation (costs 1 extra RPD per chapter)
review_threshold: 75.0 # chapters scoring below this are flagged for human review

# ── Misc ──────────────────────────────────────────────────────────────────────
verbose: false # show DEBUG-level logs
```

### Key settings to tune

| Setting          | Recommendation                                                                     |
| ---------------- | ---------------------------------------------------------------------------------- |
| `batch_size`     | Lower (2) if you hit token limits; raise (8) for short chapters                    |
| `context_window` | `2`–`5` for ongoing stories; `1`–`2` for standalone; `~` to use all prior chapters |

Why gemini-3-flash-preview? Flash models reduce thinking which does not beneficial in translation and may increases output token.

---

## Data Files

### Glossary (`data/glossaries/*.yaml`)

> **To activate:** copy the example file and remove the `example_` prefix.
> Files starting with `example_` are ignored by the translator.
>
> ```bash
> cp data/glossaries/example_glossary.yaml data/glossaries/my_series_glossary.yaml
> ```

```yaml
entries:
    - source: "Sword Saint"
      target: "Kiếm Thánh"
      context: "Danh hiệu"
      notes: ""
```

Multiple files are merged automatically. All entries are injected into every translation prompt.

### Relationship Matrix (`data/relationships/*.yaml`)

> **To activate:** copy the example file and remove the `example_` prefix.
> Files starting with `example_` are ignored by the translator.
>
> ```bash
> cp data/relationships/example_relationships.yaml data/relationships/my_series_relationships.yaml
> ```

```yaml
relationships:
    - char_a: "Arata"
      char_b: "Yuki"
      a_calls_self: "anh"
      a_calls_b: "em"
      context: "Lãng mạn"
      notes: ""
```

Tells the model exactly which Vietnamese pronouns each character uses for themselves and others.

### Prior Volumes (`data/prior/*.epub`)

Place previously translated volumes here (sorted by filename). The chapters from the latest volume are seeded as context when translating the next volume—specifically, the last `context_window` chapters (or all chapters if `context_window: ~`).

```
data/prior/
├── vol01_vi.epub
├── vol02_vi.epub
└── vol03_vi.epub  ← last N chapters seeded when translating vol04
```

---

## Checkpoint / Resume

Translation progress is saved to `<output>.checkpoint.json` after every chapter (or batch chunk). If a run is interrupted for any reason (rate limit, Ctrl-C, crash), simply re-run `python main.py` — completed chapters are skipped automatically.

The checkpoint file is deleted when a volume finishes successfully.

To restart from scratch: delete the `.checkpoint.json` file manually (or set `resume: false` in `config.yaml`).

---

## EPUB Chapter Trimmer — `trim_epub.py`

Use this script to remove unwanted chapters (table of contents pages, newsletters, bonus inserts, etc.) **before** translating, or to clean up an already-translated EPUB.

### List chapters

```bash
python trim_epub.py my_novel.epub --list
```

```
 #  Title                              Chars
 0  Table of Contents                    412
 1  Prologue                           8,203
 2  Chapter 1: The Witch                9,841
...
17  Newsletter                           302
```

### Remove by index

```bash
# Remove specific indices
python trim_epub.py my_novel.epub --remove 0,17

# Remove a range
python trim_epub.py my_novel.epub --remove 14-18

# Combined
python trim_epub.py my_novel.epub --remove 0,14-18 -o cleaned.epub
```

### Keep a range (remove everything else)

```bash
# Keep only chapters 1–16
python trim_epub.py my_novel.epub --keep 1-16
```

### Interactive mode

Run without `--remove` or `--keep` to get a guided prompt:

```bash
python trim_epub.py my_novel.epub
```

The script prints the chapter table, asks which indices to remove, shows a preview, and asks for confirmation before writing.

### Output

- Default output: `<input>_trimmed.epub` next to the original
- Custom: `python trim_epub.py input.epub -o data/input/clean.epub`

---

## Project Structure

```
en-to-vn-ln-translate/
├── main.py                  # reads configs, translates all EPUBs in data/input/
├── trim_epub.py             # standalone EPUB chapter remover
├── config.yaml              # all settings
├── requirements.txt
├── .env.example             # template
├── translator/
│   ├── config.py            # TranslatorConfig dataclass
│   ├── checkpoint.py        # progress save/restore
│   ├── epub_handler.py      # EPUB read/write (ebooklib + BeautifulSoup)
│   ├── gemini_client.py     # Gemini API wrapper with retry logic
│   ├── glossary.py          # term consistency
│   ├── pronoun_system.py    # relationship matrix
│   ├── prompts.py           # all prompt templates
│   ├── evaluator.py         # second-pass QC
│   └── translator.py        # core pipeline
└── data/
    ├── input/               ← drop source EPUBs here
    ├── output/              ← translated EPUBs written here
    ├── glossaries/
    ├── relationships/
    └── prior/
```

---

## Translation Pipeline

```
data/input/*.epub
 └─► Extract chapters (ebooklib + BeautifulSoup)
      └─► Load checkpoint (skip already-translated chapters)
           └─► For each batch chunk:
                ├─ Build context (last N translated chapters + prior-volume seed)
                ├─ Apply Glossary + Pronoun Matrix → prompt
                ├─ [Gemini] Translate → ###CHAPTER[N]### / ###TITLE### / ###CONTENT###
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
