# Skill: AUTOFINT Nano Banana Image Prompt (Proven)

**Tanggal:** 2026-03-22
**Status:** ✅ Tested & best result

---

## Prompt Template

```
Reference images:
1. [attach Ternakuang grid] — follow these DESIGN VARIATIONS. Match the layout style, composition, editorial photography, typography weight, and visual variety shown across all posts. Each post uses a different creative variation — sometimes text overlay on full photo, sometimes text left with photo right, sometimes colored highlight boxes behind subtitles, sometimes small label tags at top. Choose the best variation that fits the topic context.

Create an Instagram post image (1080x1350px, 4:5 portrait ratio).

Topic: {TOPIC_CONTEXT}

Font: Akkordeon Eleven or Bebas Neue for headline (ultra condensed, heavy, ALL CAPS)
Font: Sohne or Inter for subtitle

Text (must appear exactly):
- Headline: "{HEADLINE}"
- Subtitle: "{SUBTITLE}"

Colors: Neon blue (#00D4FF) for highlights/lines, white for text, orange (#F97316) for CTA only. Dark gradient background, never flat black.

Choose the most compelling design variation from reference 1 that best fits this topic. Be creative.

Output: 1080x1350px (4:5 portrait), photorealistic editorial style.
```

## Variables
- `{TOPIC_CONTEXT}` — deskripsi topik slide (dari Agent 1 output)
- `{HEADLINE}` — headline ALL CAPS dari slide script
- `{SUBTITLE}` — subtitle dari slide script

## Notes
- Selalu attach 1 reference: Ternakuang grid screenshot
- Grid reference disimpan di GDrive: folder `1Fs4omUgqxLPuTLLdH1aPT3esyzTOJqnu`
- Model: imagen-3.0-generate-002
- Ratio: 4:5 (1080x1350px)
- Jangan pakai flat black — selalu dark gradient
- Orange HANYA untuk CTA elements

## Tested Result
- Topik: "THR Cuma Numpang Lewat" → hasil sangat memuaskan
- Variasi layout dipilih AI sesuai konteks topik
