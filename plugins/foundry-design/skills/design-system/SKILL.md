---
name: design-system
description: Create or update the project's design system reference file (design/design-system.md) from a fill-in template - color tokens with contrast-checked pairs, type scale, spacing ladder, radii, elevation, motion, component rules and vocabulary - so specs, reviews and the design gate all grade against one source of truth. Use when a project has no written design system, when tokens drift from the docs, or before the first UI spec. Triggers - "set up a design system", "document our tokens", "design tokens", "type scale", "spacing scale", "what colors do we use", "make our UI consistent", "fill in the design system".
---

# Design system: one file every spec and review grades against

## Why this exists

`ui-ux-spec`, the `ui-reviewer` agent and `design-critique` all say "use the design system".
They need one file to point at. This skill produces `design/design-system.md` from the template
in `${CLAUDE_SKILL_DIR}/references/design-system.md`, filled with YOUR project's values.
It is a pluggable reference: swap the file and every other tool in this plugin follows it.

The CSS (or theme file) stays the source of truth. This document is the reading guide that names
each token, says when to use it, and records the rules a reviewer can check.

## Workflow

### If the project already has styles

1. **List the style and component files.** Never assume `src/`: styles live in `public/css/`,
   `app/`, `assets/` and elsewhere. Use the tracked files, with `find` as the fallback outside
   git. The extraction below repeats this list so each command block runs on its own:

   ```bash
   files() { { git ls-files -- '*.css' '*.scss' '*.sass' '*.less' '*.html' '*.tsx' '*.jsx' '*.vue' '*.svelte' '*.astro' 2>/dev/null | grep . ; } \
     || find . \( -name node_modules -o -name .git -o -name dist -o -name build -o -name .next \) -prune -o -type f \
          \( -name '*.css' -o -name '*.scss' -o -name '*.sass' -o -name '*.less' -o -name '*.html' -o -name '*.tsx' \
             -o -name '*.jsx' -o -name '*.vue' -o -name '*.svelte' -o -name '*.astro' \) -print; }
   files | head -40
   # token source: CSS custom properties, plus a Tailwind config or theme file
   files | tr '\n' '\0' | xargs -0 grep -lE -- '--[a-z0-9-]+:[[:space:]]' 2>/dev/null | head
   ls -a | grep -iE '^tailwind\.config'; files | grep -iE 'theme|tokens' | head
   ```

   If the list is empty, the project has no style files yet: treat it as greenfield (below).

2. **Extract what is actually used**, not what you wish were used (same `files` list):

   ```bash
   files() { { git ls-files -- '*.css' '*.scss' '*.sass' '*.less' '*.html' '*.tsx' '*.jsx' '*.vue' '*.svelte' '*.astro' 2>/dev/null | grep . ; } \
     || find . \( -name node_modules -o -name .git -o -name dist -o -name build -o -name .next \) -prune -o -type f \
          \( -name '*.css' -o -name '*.scss' -o -name '*.sass' -o -name '*.less' -o -name '*.html' -o -name '*.tsx' \
             -o -name '*.jsx' -o -name '*.vue' -o -name '*.svelte' -o -name '*.astro' \) -print; }
   g() { files | tr '\n' '\0' | xargs -0 grep -hoE "$1" 2>/dev/null; }
   # raw colors (each one is a token you are missing, or drift)
   g '#[0-9a-fA-F]{3,8}\b' | sort | uniq -c | sort -rn | head -30
   # font sizes and weights in use
   g 'font-size:[[:space:]]*[0-9.]+(px|rem|em)' | sed -E 's/font-size:[[:space:]]*//' | sort | uniq -c | sort -rn
   g 'font-weight:[[:space:]]*[0-9]+' | sed -E 's/font-weight:[[:space:]]*//' | sort | uniq -c | sort -rn
   # spacing values in use
   g '(margin|padding|gap)[a-z-]*:[[:space:]]*[0-9]+px' | grep -oE '[0-9]+px' | sort -n | uniq -c
   ```

3. **Collapse to a system.** Pick the smallest set that covers real use: usually 4-6 surface
   colors, 3-4 text tiers, one accent with hover/active states, 4 status colors, a type scale of
   5-7 sizes, 3-4 weights, a spacing ladder of 8-10 steps, 2-3 radii. Every value you drop gets a
   "replace with" note in the migration section.
4. **Check every text/background pair you list** for contrast (4.5:1 body, 3:1 large text and UI
   boundaries). Use the gate's color math (`${CLAUDE_SKILL_DIR}/scripts/design_gate.py`, stdlib only):

   ```bash
   PYTHONPATH="${CLAUDE_SKILL_DIR}/scripts" python3 - <<'EOF'
   from design_gate import parse_color, contrast_ratio
   pairs = {"text-1 on canvas": ("#1a1a1a", "#ffffff"), "text-3 on surface-2": ("#6b6b6b", "#f4f4f5")}
   for name, (fg, bg) in pairs.items():
       print(f"{name}: {contrast_ratio(parse_color(fg), parse_color(bg)):.2f}:1")
   EOF
   ```

   Record the ratio next to each pair in the template's contrast table. A pair under the
   threshold is either fixed or marked "large text only" or "disabled only".
5. **Fill `${CLAUDE_SKILL_DIR}/references/design-system.md`** into `design/design-system.md`. Delete the guidance
   comments as you fill each section.

### If the project is greenfield

1. Decide the aesthetic direction first. For that, use Anthropic's official `frontend-design`
   skill (in the `claude-plugins-official` marketplace); it is built for choosing a visual point
   of view. Come back here to pin the result down as tokens and rules.
2. Fill the template with the chosen values, run the contrast check above, and write the tokens
   into your CSS or theme file in the same commit.

## Rules the template asks you to decide (and reviewers will check)

- **Primary action rule:** how many filled primary buttons per screen (recommended: one).
  `design_gate.py` enforces this with `limits.max_primary_buttons` and the `primary_button`
  selector, so record the exact selector (for example `[data-variant='primary']`).
- **Status vs accent:** status colors (success, warning, danger, info) never reuse the brand accent.
- **Elevation rule:** shadows, or lighter surfaces, or borders. Pick one primary method.
- **Theme support:** light, dark, or both. If both, every token has both values.
- **Vocabulary:** one name per act ("Delete" or "Remove", never both). Copy the table into
  `design/vocabulary.md` so `design-critique` can enforce it.

## Acceptance check

- [ ] Every color, size, radius, duration used in components maps to a named token in the file.
- [ ] Every listed text/background pair has a measured contrast ratio, and all body pairs are >= 4.5:1.
- [ ] Type scale, weights and spacing ladder are each a short explicit list.
- [ ] The primary button selector is recorded and matches the code.
- [ ] The migration table lists every dropped raw value with its replacement token.
- [ ] `design/vocabulary.md` exists with at least the core-flow verbs.
