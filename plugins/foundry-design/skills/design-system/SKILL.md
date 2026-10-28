---
name: design-system
description: Create or update the project's design system reference file (design/design-system.md) from a fill-in template - color tokens with contrast-checked pairs, type scale, spacing ladder, radii, elevation, motion, component rules and vocabulary - so specs, reviews and the design gate all grade against one source of truth. Use when a project has no written design system, when tokens drift from the docs, or before the first UI spec. Triggers - "set up a design system", "document our tokens", "design tokens", "type scale", "spacing scale", "what colors do we use", "make our UI consistent", "fill in the design system".
---

# Design system: one file every spec and review grades against

## Why this exists

`ui-ux-spec`, the `ui-reviewer` agent and `design-critique` all say "use the design system".
They need one file to point at. This skill produces `design/design-system.md` from the template
in `references/design-system.md` (in this skill's directory), filled with YOUR project's values.
It is a pluggable reference: swap the file and every other tool in this plugin follows it.

The CSS (or theme file) stays the source of truth. This document is the reading guide that names
each token, says when to use it, and records the rules a reviewer can check.

## Workflow

### If the project already has styles

1. **Find the token source.** Look for CSS custom properties, a Tailwind config, or a theme file:

   ```bash
   grep -rlE -- '--[a-z0-9-]+:\s' src styles app 2>/dev/null | head
   ls tailwind.config.* src/theme* src/styles 2>/dev/null
   ```

2. **Extract what is actually used**, not what you wish were used:

   ```bash
   # raw colors in components (each one is a token you are missing, or drift)
   grep -rnoE '#[0-9a-fA-F]{3,8}\b' src --include='*.css' --include='*.tsx' --include='*.jsx' | sort | uniq -c | sort -rn | head -30
   # font sizes and weights in use
   grep -rnoE 'font-size:\s*[0-9.]+(px|rem)' src | sed 's/.*font-size:\s*//' | sort | uniq -c | sort -rn
   grep -rnoE 'font-weight:\s*[0-9]+' src | sed 's/.*font-weight:\s*//' | sort | uniq -c | sort -rn
   # spacing values in use
   grep -rnoE '(margin|padding|gap)[a-z-]*:\s*[0-9]+px' src | grep -oE '[0-9]+px' | sort -n | uniq -c
   ```

3. **Collapse to a system.** Pick the smallest set that covers real use: usually 4-6 surface
   colors, 3-4 text tiers, one accent with hover/active states, 4 status colors, a type scale of
   5-7 sizes, 3-4 weights, a spacing ladder of 8-10 steps, 2-3 radii. Every value you drop gets a
   "replace with" note in the migration section.
4. **Check every text/background pair you list** for contrast (4.5:1 body, 3:1 large text and UI
   boundaries). Use the plugin's color math:

   ```bash
   python3 - <<'EOF'
   import sys, glob, os
   gate = glob.glob(os.path.expanduser("~/.claude/plugins/**/foundry-design/scripts/design_gate.py"), recursive=True)
   sys.path.insert(0, os.path.dirname(gate[0]))   # or the plugin's scripts/ dir if installed elsewhere
   from design_gate import parse_color, contrast_ratio
   pairs = {"text-1 on canvas": ("#1a1a1a", "#ffffff"), "text-3 on surface-2": ("#6b6b6b", "#f4f4f5")}
   for name, (fg, bg) in pairs.items():
       print(f"{name}: {contrast_ratio(parse_color(fg), parse_color(bg)):.2f}:1")
   EOF
   ```

   Record the ratio next to each pair in the template's contrast table. A pair under the
   threshold is either fixed or marked "large text only" or "disabled only".
5. **Fill `references/design-system.md`** into `design/design-system.md`. Delete the guidance
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
