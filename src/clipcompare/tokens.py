"""Colours and type from the Pika design system (@mellis-labs/design-system 2.5.0).

Each constant is named after the `--ds-*` token it copies, so a design-system
change is a find-and-replace away. Values are written the way ffmpeg filters
take them (`0xRRGGBB`, `@alpha` for translucent tokens); the video is always a
dark surface, so translucent tokens use their dark-theme value.
"""

from __future__ import annotations

DS_BLACK = "0x111111"              # --ds-black: waveform panel background
DS_EGGSHELL = "0xfcfaf7"           # --ds-eggshell (dark --ds-text-primary): label text
DS_ACCENT_700 = "0xcfc3ff"         # --ds-accent-700 = --ds-brand / --ds-lilac: waveform, highlight
DS_TEXT_SECONDARY_DARK = "0xfcfaf7@0.7"  # dark --ds-text-secondary, #fcfaf7b3: diff summary, notes
DS_INVERT_600_DARK = "0x222222@0.6"   # dark --ds-invert-600, rgb(34 34 34 / 60%): label chip
DS_PRIMARY_300_DARK = "0xfcfaf7@0.1"  # dark --ds-primary-300, rgb(252 250 247 / 10%): centre line
DS_NEON_GREEN = "0x15cb74"         # --ds-neon-green: a similarity close to the baseline
DS_ALERT = "0xde0000"              # --ds-alert (= --ds-destructive): a similarity far from it

# --ds-font-sans is "Telka" (labels), --ds-font-display "Telka Extended"
# (titles), both at the Medium weight. Telka is a licensed commercial face
# that the design system only serves from Pika's CDN, so it is not bundled:
# it is used when installed on this machine, and TikTok Sans stands in when not.
DS_FONT_SANS = "Telka-Medium.otf"
DS_FONT_BODY = "Telka-Regular.otf"   # --ds-font-sans at the copy weight: caption text
DS_FONT_DISPLAY = "Telka-ExtendedMedium.otf"
