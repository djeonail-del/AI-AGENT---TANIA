# Skill: Baca File .docx dari Telegram

**Tanggal:** 2026-03-22
**Trigger:** User kirim file .docx via Telegram, minta dibaca

---

## Problem

File .docx adalah format binary — tidak bisa langsung dibaca sebagai teks. Perlu convert dulu.

## Solution

Gunakan `python-docx` via virtual environment (karena macOS externally-managed environment):

```bash
# Buat venv dulu
python3 -m venv /tmp/docx-venv

# Install python-docx
/tmp/docx-venv/bin/pip install python-docx -q

# Baca file
/tmp/docx-venv/bin/python3 -c "
from docx import Document
doc = Document('/path/to/file.docx')
for p in doc.paragraphs:
    if p.text.strip():
        print(p.text)
"
```

## Notes

- File inbound dari Telegram tersimpan di: `/Users/mac/.openclaw/media/inbound/`
- `pandoc` bisa jadi alternatif tapi belum terinstall di sistem ini
- venv di `/tmp/` akan hilang setelah restart — buat ulang kalau perlu
- Tabel di dalam docx tidak terbaca dengan cara ini, hanya paragraf biasa

## Status

✅ Tested & working — 2026-03-22
