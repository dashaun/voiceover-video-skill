---
name: kimi-video
description: "Create polished, on-brand vertical videos for Kimi and Moonshot AI content. A Kimi-flavoured wrapper around the local voiceover-video engine: word-level captions, timed shot lists, dynamic themes, synthesized sound design, and frame-exact rendering. Use when asked to 'make a Kimi video', 'create a Moonshot explainer', 'turn this voice note into a Kimi Short', or any content where you want to showcase Kimi, Kimi K3, or Moonshot AI."
---

# Kimi Video Skill

This skill is a Kimi-branded edition of the `voiceover-video` engine. Everything that makes the
engine work — transcription, rendering, audio, encoding — lives in `../voiceover-video/scripts/` and
`../voiceover-video/templates/`. This SKILL.md only changes the defaults, the brand, and the
recommended shot vocabulary so the result feels native to Kimi and Moonshot AI.

`SKILL_DIR` = the directory containing this SKILL.md.
`ENGINE_DIR` = `SKILL_DIR/../voiceover-video`.

**Always load `ENGINE_DIR/references/scene-blocks.md` before writing the shot list.**

---

## What makes this the Kimi edition

- **Default brand** is tuned for Kimi/Moonshot AI: deep space-purple background, violet + cyan
  accents, Outfit display type and JetBrains Mono code type.
- **Default theme** is `aurora` (frosted glass, soft gradients, modern) — ideal for AI product
  launches and dev-tool explainers. Fall back to `kinetic` for hot takes and `retro` for
  history-of-tech stories.
- **Shot vocabulary** leans on `diagram`, `logo-wall`, `terminal`, `lower-third`, and `clip` blocks
  because Kimi content is usually about models, APIs, context windows, and code.
- **Output folder** defaults to `~/kimi-videos`.

---

## Step 0 — Gather inputs

Same as `voiceover-video` SKILL.md Step 0, with these defaults:

| Field | Default |
|---|---|
| `template` | `aurora` |
| `format` | `vertical` 1080×1920 |
| `music` | `synth` |
| `model` | `small` |
| `slug` | `kimi-<topic>` e.g. `kimi-k3-demystified` |

Brand resolution: `./brand.json`, then `~/.config/kimi-video/brand.json`, then
`SKILL_DIR/brand.example.json`.

Create the work directory:

```bash
mkdir -p <brand.output.dir>/<slug>/work
work="<brand.output.dir>/<slug>/work"
```

**First run only — no brand file anywhere:** ask the four brand questions. Suggested defaults for
Kimi ambassador content:

| Ask | Default |
|---|---|
| Handle | required, no default |
| Look | `kimi-purple` (deep purple + violet/cyan) |
| Fonts | `Outfit` / `JetBrains Mono` |
| Output dir | `~/kimi-videos` |

Use `init_brand.py` from the engine:

```bash
python3 ENGINE_DIR/scripts/init_brand.py --handle @theirhandle --preset kimi-purple \
  [--heading Outfit --mono 'JetBrains Mono'] [--output-dir ~/kimi-videos]
```

---

## Step 1 — Setup

```bash
bash ENGINE_DIR/scripts/setup.sh
```

This installs playwright-core, Chromium, GSAP, and downloads the brand fonts into
`ENGINE_DIR/assets/`.

---

## Steps 2–5 — Transcribe, captions, shot list, images

Follow `voiceover-video` SKILL.md Steps 2–5.

When you write the shot list, prefer blocks that suit Kimi content:

- `diagram` — MoE routing, context-window flow, API request lifecycle
- `logo-wall` — Kimi + Hugging Face + Spring AI + Java logos
- `terminal` — API calls, `application.properties`, curl examples
- `counter` — 2.8T parameters, 1M context, 1TB memory
- `lower-third` — speaker name / "Engineering Ambassador" / "Kimi K3"
- `clip` — short screen recordings of the Kimi app or Kimi API playground
- `quote` — pull quotes from the voiceover

For images, use the new media tools:

```bash
python3 ENGINE_DIR/scripts/find_media.py --query "Kimi chatbot interface" --outdir "$work/assets"
bash ENGINE_DIR/scripts/extract_clip.sh <screen-recording.mp4> "$work/assets/kimi-demo.mp4" <start> <end>
```

---

## Step 6 — Author the composition

```bash
python3 ENGINE_DIR/scripts/fill_template.py "$work" <duration> --format vertical --template aurora
# or --template kinetic / retro / documentary / newsroom / blueprint / brutalist
```

Replace the demo shots and timeline with your Kimi shot list. Use the helpers defined in
`ENGINE_DIR/templates/kinetic.html`.

---

## Steps 7–11 — QA, sound, frames, mix, verify

Follow `voiceover-video` SKILL.md Steps 7–11.

---

## Non-negotiables

Same as `voiceover-video`, plus:

- **Keep the Kimi brand honest.** Do not invent product features, pricing, or dates. If a claim is
  approximate (e.g. "roughly 1 TB"), say so in the report.
- **Credit Moonshot AI and Kimi logos** if they appear as primary visuals; keep a credits list.
- **Disclose ambassadorship** if the video is being posted publicly — the skill's default outro can
  include "Engineering Ambassador" or a plain "opinions are my own" note.
- **Use approved colors** from the brand file; do not introduce random accent colors.

---

## Example prompt for the agent

> make a Kimi video out of ~/Downloads/kimi-k3-take.m4a

The agent will transcribe, choose `aurora`, build a Kimi-focused shot list, and render a vertical
Short ready for posting.
