# Skill: AutoResearch Pattern (Karpathy)

**Tanggal:** 2026-04-23
**Source:** https://github.com/karpathy/autoresearch
**Trigger:** Butuh automation loop yang iterate strategi → test → keep/discard, tanpa intervensi manual

---

## Konsep Inti

> Kasih AI agent satu file kerja + metric tunggal + time budget fixed → biarkan dia experiment overnight. Kalau hasil lebih baik → commit. Kalau tidak → reset. Repeat forever.

Filosofi Karpathy: **One GPU, one file, one metric.**

## Kenapa Pola Ini Powerful

- Manual tweaking bias + capek → AI bisa run 100 experiments saat human tidur
- Metric tunggal + time budget fixed → hasil selalu comparable
- Single-file edit + git commit per experiment → diff reviewable, mudah rewind
- Branch isolation → master tetap bersih

## Tiga Komponen Wajib

| Komponen | Siapa Edit | Isi |
|----------|-----------|-----|
| `prepare.py` (atau equivalent) | **Read-only** | Konstanta, data, ground-truth metric function |
| `train.py` (atau equivalent) | **AI agent** | Logic yang di-iterate (strategi, arsitektur, hyperparameter) |
| `program.md` | **Human** | Skill spec: rules, goal, constraints, output format |

## Loop Wajib (copy dari program.md Karpathy)

```
LOOP FOREVER:
  1. Cek git state (branch/commit sekarang)
  2. Edit file target dengan ide baru
  3. git commit
  4. Run experiment → redirect ke run.log (jangan flood context)
  5. grep metric dari log
  6. Kalau crash → tail log → fix kalau simple, skip kalau fundamental
  7. Log ke results.tsv (NOT git-tracked)
  8. Kalau metric improve → keep commit (advance branch)
  9. Kalau sama/worse → git reset
```

## Aturan Agent Krusial

1. **NEVER STOP** — sekali loop mulai, JANGAN tanya "should I continue?". Human mungkin tidur. Run sampai di-interrupt manual.
2. **Simplicity criterion** — improvement kecil + code messy = reject. Hapus code + hasil sama = keep (simplification win).
3. **No new deps** — cuma pakai yang ada di pyproject/deps.
4. **Don't touch evaluation** — ground-truth metric function harus untouchable.
5. **Time budget fixed** — biar comparable. Kalau overrun >2x → kill + discard.

## Logging Format (TSV, bukan CSV — comma bisa break)

```
commit  metric    status   description
a1b2c3d 0.9979    keep     baseline
b2c3d4e 0.9932    keep     increase LR to 0.04
c3d4e5f 1.0050    discard  switch to GeLU activation
d4e5f6g 0.0000    crash    double model width (OOM)
```

## Setup Pattern (pakai Claude Code)

1. Buat branch: `git checkout -b autoresearch/<tag>`
2. Spawn Claude Code: `claude`
3. Prompt:
   ```
   Hi have a look at program.md and let's kick off a new experiment!
   Let's do the setup first. Use ask_user_question until you reach clarity.
   ```
4. Agent baca program.md → tanya klarifikasi → mulai loop

## Adaptasi ke Domain Non-LLM

Pola ini generic — bisa dipakai untuk apapun yang punya metric tunggal:

| Domain | `train.py` equivalent | Metric (`val_bpb` equivalent) |
|--------|----------------------|------------------------------|
| LLM training (original) | Model + optimizer + training loop | `val_bpb` (lower better) |
| Trading bot | Strategy code (indicator rules, position sizing) | Sharpe ratio on backtest (higher better) |
| AUTOFINT carousel | Prompt generator / hook templates | Engagement score (sim or real) |
| SMM scheduling | Posting time + caption style logic | CTR / save rate |
| Ad copy | Creative generator | Conversion rate proxy |

**Kunci adaptasi:**
- Data split **train/test yang bersih** — agent TIDAK boleh lihat test data pas design strategy
- **Look-ahead bias guard** kalau domain butuh (trading wajib — kalau metric "too perfect", reject)
- Time budget fixed bisa diganti "compute budget" atau "API call budget"

## Gotchas

- **Reward hacking** — agent bisa "cheat" kalau metric bocor (mis. akses test data). Karpathy untungnya pakai vocab-independent metric + separate val shard yang dipin.
- **Local minima** — loop bisa stuck tweaking kecil. Kalau stuck: re-read papers, coba radical changes, combine near-misses. Rewind branch dipakai **sangat jarang**.
- **Context flood** — `uv run train.py > run.log 2>&1`. Jangan pakai `tee`. Cuma grep metric yang dibutuhkan.
- **Results.tsv tracked accidentally** — add ke .gitignore atau selalu leave untracked.

## Notable Forks (non-H100)

- `miolini/autoresearch-macos` — MacOS CPU
- `trevin-creator/autoresearch-mlx` — MacOS dengan MLX (Apple Silicon GPU)
- `jsegov/autoresearch-win-rtx` — Windows + RTX
- `andyluo7/autoresearch` — AMD GPU

## Tips Hardware Kecil (Karpathy's recs)

1. Pakai **TinyStories dataset** (entropy rendah → model kecil decent)
2. `vocab_size`: 8192 → 4096 → 2048 → byte-level (256)
3. `MAX_SEQ_LEN`: turun ke 256, naikin `DEVICE_BATCH_SIZE`
4. `EVAL_TOKENS`: turunin
5. `DEPTH`: 8 → 4
6. `WINDOW_PATTERN`: "L" doang (skip banded attention)
7. `TOTAL_BATCH_SIZE`: `2**14` (16K), keep power of 2

## Perbandingan dengan Pola Automation Lain

| Pola | Durasi | Lokasi | Use Case |
|------|--------|--------|----------|
| `/loop` skill | Selama sesi CLI | Lokal | Polling status, cek recurring singkat |
| Claude Code Routines | Terjadwal | Cloud | Tugas rutin (daily PR review, reports) |
| **AutoResearch** | **Forever until interrupt** | **Lokal/cloud compute** | **Iterative optimization dengan metric** |

AutoResearch ≠ Routines ≠ Loop. Ini eksperimen scientific loop, bukan scheduled task.

## Status

✅ Dipelajari — 2026-04-23
