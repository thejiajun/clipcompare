# Bundled font

`TikTokSans-Medium.ttf` — TikTok Sans by TikTok Inc., SIL Open Font License 1.1.
https://github.com/tiktok/TikTokSans

Instanced from the upstream variable font at `wght=500, opsz=36, wdth=100,
slnt=0`. The variable font's own default instance is Light (`wght=300`), which
FreeType would otherwise pick — too thin for a label sitting over video.

The face covers Latin and extended Latin only (910 glyphs, no CJK), so
`fonts.py` falls back to a system face for non-Latin labels.
