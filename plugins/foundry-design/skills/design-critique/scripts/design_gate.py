#!/usr/bin/env python3
"""design_gate.py - the objective, deterministic half of the design-critique gate.

No model and no taste. It measures the countable signals that friction regressions
show up in, and fails the build when they get worse or break a hard limit:

  flow.<name>.clicks            clicks from start to goal on a core flow     (C1, C6)
  flow.<name>.reached           the flow still reaches its goal              (core flow works)
  page.<p>@<vp>.dead_controls   disabled / aria-disabled buttons on screen   (C3)
  page.<p>@<vp>.entry_points    navigation controls (surface-count proxy)    (C5, C8)
  page.<p>@<vp>.primary_buttons visible primary-styled buttons               (one primary per screen)
  page.<p>@<vp>.small_target_count  targets under the touch / pointer minimum (WCAG 2.5.8, Fitts)
  page.<p>@<vp>.contrast_failure_count  text below 4.5:1 (3:1 for large)     (WCAG 1.4.3)
  page.<p>@<vp>.unlabeled_buttons  buttons with no accessible name           (WCAG 4.1.2)
  page.<p>@<vp>.inputs_under_16px  touch inputs under 16px (iOS zoom)
  page.<p>@<vp>.h_scroll        horizontal page scroll                       (layout floor)
  context.<name>.present        a must-always-be-visible element is present  (C4)

Subcommands:
  measure --config CFG [--out FILE]     drive the app with Playwright, write metrics JSON
  check   --current FILE [--baseline FILE] [--config CFG]   compare, exit 1 on regression
  bless   --current FILE --baseline FILE                    accept current as the baseline
  run     --config CFG [--bless]        measure, then check (or bless)

Only `measure` and `run` need Playwright (pip install playwright && python -m playwright
install chromium). `check` and `bless` are stdlib only, so any collector in any language
can write the metrics JSON and reuse the comparison.

Exit codes: 0 pass, 1 design regression or limit violation, 2 usage/config error,
3 refused a non-local target (set "allow_remote": true only for a read-only target).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from urllib.parse import urlparse

# --------------------------------------------------------------------------- defaults

DEFAULT_LIMITS = {
    "max_primary_buttons": 1,      # one filled primary action per screen
    "min_touch_target": 44,        # px, Apple HIG / Material guidance for touch primaries
    "min_pointer_target": 24,      # px, WCAG 2.2 SC 2.5.8 (AA)
    "min_contrast": 4.5,           # WCAG 1.4.3 normal text
    "min_contrast_large": 3.0,     # WCAG 1.4.3 large text (>=24px, or >=18.66px and bold)
    "min_input_font_px_touch": 16, # below this iOS Safari zooms on focus
    "allow_horizontal_scroll": False,
    "max_small_targets": 0,        # absolute cap; null disables, baseline still applies
    "max_contrast_failures": 0,
    "max_unlabeled_buttons": 0,
}

DEFAULT_SELECTORS = {
    "primary_button": "[data-variant='primary'], .btn-primary, button[type='submit'].primary",
    "entry_points": "nav a, nav button, [role='navigation'] a, [role='tablist'] [role='tab']",
    "interactive": "a[href], button, input:not([type='hidden']), select, textarea, "
                   "[role='button'], [role='link'], [role='checkbox'], [role='tab'], "
                   "[tabindex]:not([tabindex='-1'])",
}

DEFAULT_VIEWPORTS = {
    "phone": {"width": 390, "height": 844, "touch": True},
    "desktop": {"width": 1440, "height": 900, "touch": False},
}

# Metric name suffixes where a larger number is worse.
LOWER_IS_BETTER = (
    "dead_controls", "entry_points", "primary_buttons", "small_target_count",
    "contrast_failure_count", "unlabeled_buttons", "inputs_under_16px", "clicks",
)
# Booleans that must stay true once true.
MUST_HOLD = ("reached", "present")
# Booleans where true is bad.
MUST_STAY_FALSE = ("h_scroll",)

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}

# --------------------------------------------------------------------------- color math


class ColorError(ValueError):
    pass


_RGB_RE = re.compile(r"rgba?\(\s*([^)]*)\)", re.I)


def parse_color(value: str) -> tuple[float, float, float, float]:
    """Parse a computed CSS color ('rgb(1, 2, 3)', 'rgba(1,2,3,0.5)', 'rgb(1 2 3 / 50%)',
    '#abc', '#aabbcc', '#aabbccdd', 'transparent') into (r, g, b, a) with r,g,b in 0..255."""
    if value is None:
        raise ColorError("no color")
    v = value.strip().lower()
    if v == "transparent":
        return (0.0, 0.0, 0.0, 0.0)
    if v.startswith("#"):
        h = v[1:]
        if len(h) in (3, 4):
            h = "".join(c * 2 for c in h)
        if len(h) not in (6, 8) or not re.fullmatch(r"[0-9a-f]+", h):
            raise ColorError(f"bad hex color {value!r}")
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
        a = int(h[6:8], 16) / 255 if len(h) == 8 else 1.0
        return (float(r), float(g), float(b), a)
    m = _RGB_RE.fullmatch(v)
    if not m:
        raise ColorError(f"unsupported color {value!r} (expected computed rgb/rgba)")
    parts = [p for p in re.split(r"[\s,/]+", m.group(1).strip()) if p]
    if len(parts) not in (3, 4):
        raise ColorError(f"bad rgb color {value!r}")

    def chan(p: str) -> float:
        return float(p[:-1]) * 2.55 if p.endswith("%") else float(p)

    r, g, b = (max(0.0, min(255.0, chan(p))) for p in parts[:3])
    a = 1.0
    if len(parts) == 4:
        p = parts[3]
        a = float(p[:-1]) / 100 if p.endswith("%") else float(p)
        a = max(0.0, min(1.0, a))
    return (r, g, b, a)


def composite(top: tuple, bottom: tuple) -> tuple:
    """Alpha-composite `top` over an opaque-or-not `bottom` (source-over)."""
    ta, ba = top[3], bottom[3]
    out_a = ta + ba * (1 - ta)
    if out_a == 0:
        return (0.0, 0.0, 0.0, 0.0)
    chans = tuple((top[i] * ta + bottom[i] * ba * (1 - ta)) / out_a for i in range(3))
    return (*chans, out_a)


def resolve_background(layers: list[str], page_bg: str = "rgb(255, 255, 255)") -> tuple:
    """`layers` are computed background colors from the element outward (innermost first).
    Composite them, innermost on top, over the page background, and return an opaque color."""
    result = parse_color(page_bg)
    if result[3] < 1:
        result = composite(result, (255.0, 255.0, 255.0, 1.0))
    for layer in reversed(layers):  # paint outermost first
        c = parse_color(layer)
        if c[3] > 0:
            result = composite(c, result)
    return result


def relative_luminance(c: tuple) -> float:
    def lin(x: float) -> float:
        s = x / 255
        return s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4

    r, g, b = (lin(c[i]) for i in range(3))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(fg: tuple, bg: tuple) -> float:
    """WCAG contrast ratio. `fg` may be translucent; it is composited over the opaque `bg`."""
    if fg[3] < 1:
        fg = composite(fg, bg)
    l1, l2 = relative_luminance(fg), relative_luminance(bg)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def is_large_text(size_px: float, weight: float) -> bool:
    """WCAG large text: >= 18pt (24px), or >= 14pt (18.66px) and bold (>= 700)."""
    return size_px >= 24 or (size_px >= 18.66 and weight >= 700)


# --------------------------------------------------------------------------- page evaluation


def evaluate_page(raw: dict, limits: dict) -> tuple[dict, dict]:
    """Turn one page's raw browser facts into (metrics, details). Pure function.

    raw = {
      "touch": bool, "inner_width": int, "scroll_width": int,
      "dead_controls": int, "entry_points": int, "primary_buttons": int,
      "unlabeled_buttons": int, "inputs_font_px": [float, ...],
      "targets": [{"w":..,"h":..,"label":..,"inline":bool}, ...],
      "text_samples": [{"fg":"rgb()", "bg_layers":["rgba()",...], "bg_image":bool,
                        "size":px, "weight":n, "text":".."}, ...],
      "page_bg": "rgb()"  (optional)
    }
    """
    lim = {**DEFAULT_LIMITS, **(limits or {})}
    touch = bool(raw.get("touch"))
    min_target = lim["min_touch_target"] if touch else lim["min_pointer_target"]

    small = []
    for t in raw.get("targets", []):
        if t.get("inline"):
            continue  # WCAG 2.5.8 exempts targets inside a sentence
        w, h = t.get("w", 0), t.get("h", 0)
        if w <= 1 or h <= 1:
            continue  # visually hidden (skip links, sr-only)
        if w < min_target or h < min_target:
            small.append({"label": t.get("label", ""), "w": w, "h": h})

    failures, unknown = [], 0
    for s in raw.get("text_samples", []):
        if s.get("bg_image"):
            unknown += 1
            continue
        try:
            fg = parse_color(s["fg"])
            bg = resolve_background(s.get("bg_layers", []), raw.get("page_bg") or "rgb(255, 255, 255)")
        except (ColorError, KeyError):
            unknown += 1
            continue
        ratio = contrast_ratio(fg, bg)
        large = is_large_text(float(s.get("size", 16)), float(s.get("weight", 400)))
        need = lim["min_contrast_large"] if large else lim["min_contrast"]
        if ratio + 1e-9 < need:
            failures.append({"text": (s.get("text") or "")[:40], "ratio": round(ratio, 2), "need": need})

    under16 = 0
    if touch:
        under16 = sum(1 for f in raw.get("inputs_font_px", []) if f < lim["min_input_font_px_touch"])

    metrics = {
        "dead_controls": int(raw.get("dead_controls", 0)),
        "entry_points": int(raw.get("entry_points", 0)),
        "primary_buttons": int(raw.get("primary_buttons", 0)),
        "small_target_count": len(small),
        "contrast_failure_count": len(failures),
        "unlabeled_buttons": int(raw.get("unlabeled_buttons", 0)),
        "inputs_under_16px": under16,
        "h_scroll": int(raw.get("scroll_width", 0)) > int(raw.get("inner_width", 0)),
    }
    details = {"small_targets": small[:25], "contrast_failures": failures[:25], "contrast_unknown": unknown}
    return metrics, details


def absolute_violations(metrics: dict, limits: dict) -> list[str]:
    """Hard limits that fail regardless of the baseline. A null limit disables it."""
    lim = {**DEFAULT_LIMITS, **(limits or {})}
    out = []
    caps = {
        "primary_buttons": lim.get("max_primary_buttons"),
        "small_target_count": lim.get("max_small_targets"),
        "contrast_failure_count": lim.get("max_contrast_failures"),
        "unlabeled_buttons": lim.get("max_unlabeled_buttons"),
    }
    for key, value in sorted(metrics.items()):
        suffix = key.rsplit(".", 1)[-1]
        cap = caps.get(suffix)
        if cap is not None and isinstance(value, (int, float)) and not isinstance(value, bool) and value > cap:
            out.append(f"{key}: {value} exceeds limit {cap}")
        if suffix == "h_scroll" and value is True and not lim.get("allow_horizontal_scroll"):
            out.append(f"{key}: horizontal page scroll")
        if suffix == "reached" and value is False:
            out.append(f"{key}: core flow no longer reaches its goal")
    return out


def compare(current: dict, baseline: dict) -> list[str]:
    """Regressions of `current` against `baseline` (flat metric dicts)."""
    fails = []
    for key in sorted(baseline):
        base = baseline[key]
        suffix = key.rsplit(".", 1)[-1]
        if key not in current:
            fails.append(f"{key}: missing from current run (was {base!r}); a page, flow or check disappeared")
            continue
        cur = current[key]
        if suffix in MUST_HOLD:
            if base is True and cur is not True:
                fails.append(f"{key}: was true, now {cur!r} (must hold)")
        elif suffix in MUST_STAY_FALSE:
            if base is False and cur is True:
                fails.append(f"{key}: was false, now true (regressed)")
        elif suffix in LOWER_IS_BETTER:
            if isinstance(cur, (int, float)) and isinstance(base, (int, float)) and cur > base:
                fails.append(f"{key}: {base} -> {cur} (regressed, more is worse)")
    return fails


def gate(current: dict, baseline: dict | None, limits: dict | None) -> tuple[list[str], list[str]]:
    """Return (failures, notes). Failures = absolute violations + regressions."""
    fails = absolute_violations(current, limits or {})
    notes = []
    if baseline is not None:
        fails += compare(current, baseline)
        new = sorted(k for k in current if k not in baseline)
        if new:
            notes.append("new metrics not in baseline (bless to start tracking): " + ", ".join(new))
        improved = sorted(
            k for k in current
            if k in baseline and k.rsplit(".", 1)[-1] in LOWER_IS_BETTER
            and isinstance(current[k], (int, float)) and isinstance(baseline[k], (int, float))
            and current[k] < baseline[k]
        )
        if improved:
            notes.append("improved (bless to lock in): " + ", ".join(improved))
    return fails, notes


# --------------------------------------------------------------------------- config


class ConfigError(ValueError):
    pass


def load_json(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        raise ConfigError(f"file not found: {path}")
    except json.JSONDecodeError as e:
        raise ConfigError(f"invalid JSON in {path}: {e}")


def validate_config(cfg: dict) -> dict:
    if not isinstance(cfg, dict):
        raise ConfigError("config must be a JSON object")
    if not cfg.get("base_url"):
        raise ConfigError("config.base_url is required, for example http://localhost:3000")
    if not cfg.get("pages") and not cfg.get("flows"):
        raise ConfigError("config needs at least one entry in pages or flows")
    names = set()
    for p in cfg.get("pages", []):
        if "name" not in p or "path" not in p:
            raise ConfigError(f"each page needs name and path: {p}")
        names.add(p["name"])
    for f in cfg.get("flows", []):
        if "name" not in f or "goal" not in f or "steps" not in f:
            raise ConfigError(f"each flow needs name, steps and goal: {f}")
        for s in f["steps"]:
            if not any(k in s for k in ("click", "fill", "press", "goto", "wait", "eval")):
                raise ConfigError(f"flow {f['name']}: unknown step {s}")
    for vp_name, vp in (cfg.get("viewports") or {}).items():
        if not isinstance(vp.get("width"), int) or not isinstance(vp.get("height"), int):
            raise ConfigError(f"viewport {vp_name} needs integer width and height")
    return cfg


def is_local_target(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in LOCAL_HOSTS or host.endswith(".localhost") or host.endswith(".local")


def count_clicks(steps: list[dict]) -> int:
    return sum(1 for s in steps if "click" in s)


# --------------------------------------------------------------------------- browser collector

COLLECT_JS = r"""
({touch, sel}) => {
  const vis = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) return false;
    const cs = getComputedStyle(el);
    return cs.visibility !== 'hidden' && cs.display !== 'none' && parseFloat(cs.opacity) > 0;
  };
  const de = document.documentElement;
  const targets = [];
  for (const el of document.querySelectorAll(sel.interactive)) {
    if (!vis(el)) continue;
    const r = el.getBoundingClientRect();
    const inline = el.tagName === 'A' && getComputedStyle(el).display === 'inline';
    targets.push({w: Math.round(r.width), h: Math.round(r.height), inline,
      label: (el.getAttribute('aria-label') || el.textContent || el.getAttribute('name') || '').trim().slice(0, 40)});
  }
  const buttons = [...document.querySelectorAll('button, [role="button"]')].filter(vis);
  const dead = buttons.filter(b => b.disabled || b.getAttribute('aria-disabled') === 'true').length;
  const unlabeled = buttons.filter(b => !(b.textContent || '').trim() && !b.getAttribute('aria-label')
      && !b.getAttribute('aria-labelledby') && !b.getAttribute('title')).length;
  let primary = 0, entry = 0;
  try { primary = [...document.querySelectorAll(sel.primary_button)].filter(vis).length; } catch (e) { primary = -1; }
  try { entry = [...document.querySelectorAll(sel.entry_points)].filter(vis).length; } catch (e) { entry = -1; }
  const inputs = [...document.querySelectorAll('input:not([type=hidden]):not([type=checkbox]):not([type=radio]), textarea, select')]
      .filter(vis).map(i => parseFloat(getComputedStyle(i).fontSize));
  const samples = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const seen = new Set();
  while (walker.nextNode() && samples.length < 400) {
    const node = walker.currentNode;
    const text = (node.textContent || '').trim();
    const el = node.parentElement;
    if (!text || !el || seen.has(el) || !vis(el)) continue;
    if (['SCRIPT', 'STYLE', 'NOSCRIPT'].includes(el.tagName)) continue;
    seen.add(el);
    const cs = getComputedStyle(el);
    const layers = []; let bgImage = false;
    for (let a = el; a; a = a.parentElement) {
      const acs = getComputedStyle(a);
      if (acs.backgroundImage && acs.backgroundImage !== 'none') { bgImage = true; break; }
      const bg = acs.backgroundColor;
      if (bg && bg !== 'transparent' && bg !== 'rgba(0, 0, 0, 0)') {
        layers.push(bg);
        const m = bg.match(/rgba?\(([^)]*)\)/);
        const parts = m ? m[1].split(/[\s,\/]+/).filter(Boolean) : [];
        if (parts.length < 4 || parseFloat(parts[3]) >= 1) break;
      }
    }
    samples.push({fg: cs.color, bg_layers: layers, bg_image: bgImage,
                  size: parseFloat(cs.fontSize), weight: parseFloat(cs.fontWeight) || 400,
                  text: text.slice(0, 40)});
  }
  return {touch, inner_width: window.innerWidth, scroll_width: de.scrollWidth,
          dead_controls: dead, entry_points: entry, primary_buttons: primary,
          unlabeled_buttons: unlabeled, inputs_font_px: inputs, targets, text_samples: samples,
          page_bg: 'rgb(255, 255, 255)'};
}
"""


def _run_step(page, step: dict, timeout_ms: int) -> None:
    if "goto" in step:
        page.goto(step["goto"], wait_until="networkidle", timeout=timeout_ms)
    elif "click" in step:
        page.locator(step["click"]).first.click(timeout=timeout_ms)
    elif "fill" in step:
        page.locator(step["fill"]).first.fill(str(step.get("value", "")), timeout=timeout_ms)
    elif "press" in step:
        page.keyboard.press(step["press"])
    elif "eval" in step:
        page.evaluate(step["eval"])
    if "wait" in step:
        page.wait_for_timeout(int(step["wait"]))


def measure(cfg: dict, screenshots_dir: str | None = None) -> tuple[dict, dict]:
    """Drive the app and return (flat metrics, details). Requires Playwright."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise ConfigError("Playwright is not installed: pip install playwright && python -m playwright install chromium")

    base = cfg["base_url"].rstrip("/")
    sel = {**DEFAULT_SELECTORS, **(cfg.get("selectors") or {})}
    limits = {**DEFAULT_LIMITS, **(cfg.get("limits") or {})}
    viewports = cfg.get("viewports") or DEFAULT_VIEWPORTS
    timeout_ms = int(cfg.get("timeout_ms", 8000))
    settle_ms = int(cfg.get("settle_ms", 500))
    engine_name = cfg.get("engine", "chromium")
    metrics: dict = {}
    details: dict = {}

    def url(path: str) -> str:
        return path if path.startswith("http") else base + (path if path.startswith("/") else "/" + path)

    with sync_playwright() as pw:
        browser = getattr(pw, engine_name).launch(headless=True)
        try:
            for vp_name, vp in viewports.items():
                touch = bool(vp.get("touch"))
                ctx = browser.new_context(viewport={"width": vp["width"], "height": vp["height"]},
                                          has_touch=touch, is_mobile=touch and engine_name != "firefox",
                                          device_scale_factor=2 if touch else 1)
                page = ctx.new_page()
                for step in cfg.get("setup_steps", []):
                    s = dict(step)
                    if "goto" in s:
                        s["goto"] = url(s["goto"])
                    _run_step(page, s, timeout_ms)
                for p in cfg.get("pages", []):
                    page.goto(url(p["path"]), wait_until="networkidle", timeout=timeout_ms)
                    if p.get("wait_for"):
                        page.locator(p["wait_for"]).first.wait_for(timeout=timeout_ms)
                    page.wait_for_timeout(settle_ms)
                    raw = page.evaluate(COLLECT_JS, {"touch": touch, "sel": sel})
                    pm, pd = evaluate_page(raw, limits)
                    key = f"page.{p['name']}@{vp_name}"
                    for k, v in pm.items():
                        metrics[f"{key}.{k}"] = v
                    details[key] = pd
                    if screenshots_dir:
                        os.makedirs(screenshots_dir, exist_ok=True)
                        page.screenshot(path=os.path.join(screenshots_dir, f"{p['name']}@{vp_name}.png"), full_page=True)
                for f in cfg.get("flows", []):
                    if f.get("viewports") and vp_name not in f["viewports"]:
                        continue
                    key = f"flow.{f['name']}@{vp_name}"
                    reached = False
                    try:
                        page.goto(url(f.get("start", "/")), wait_until="networkidle", timeout=timeout_ms)
                        page.wait_for_timeout(settle_ms)
                        for step in f["steps"]:
                            s = dict(step)
                            if "goto" in s:
                                s["goto"] = url(s["goto"])
                            _run_step(page, s, timeout_ms)
                        page.locator(f["goal"]).first.wait_for(state="visible", timeout=timeout_ms)
                        reached = True
                    except Exception as e:  # a broken flow is a result, not a crash
                        details[key] = {"error": str(e).splitlines()[0][:200]}
                    metrics[f"{key}.clicks"] = count_clicks(f["steps"])
                    metrics[f"{key}.reached"] = reached
                for c in cfg.get("context_checks", []):
                    if c.get("viewports") and vp_name not in c["viewports"]:
                        continue
                    key = f"context.{c['name']}@{vp_name}"
                    present = False
                    try:
                        for step in c.get("steps", [{"goto": c.get("path", "/")}]):
                            s = dict(step)
                            if "goto" in s:
                                s["goto"] = url(s["goto"])
                            _run_step(page, s, timeout_ms)
                        page.wait_for_timeout(settle_ms)
                        present = page.locator(c["selector"]).first.is_visible()
                    except Exception as e:
                        details[key] = {"error": str(e).splitlines()[0][:200]}
                    metrics[f"{key}.present"] = present
                ctx.close()
        finally:
            browser.close()
    return metrics, details


# --------------------------------------------------------------------------- CLI


def _print_result(fails: list[str], notes: list[str]) -> int:
    for n in notes:
        print("note:", n)
    if fails:
        print("\nDESIGN GATE: FAIL")
        for f in fails:
            print("  x", f)
        return 1
    print("\nDESIGN GATE: PASS (no regression, no limit violation)")
    return 0


def _write_json(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
        fh.write("\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Deterministic design gate (see module docstring).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("measure", help="drive the app and write metrics JSON")
    m.add_argument("--config", required=True)
    m.add_argument("--out", default="-")
    m.add_argument("--screenshots")
    c = sub.add_parser("check", help="compare metrics against a baseline and limits")
    c.add_argument("--current", required=True)
    c.add_argument("--baseline")
    c.add_argument("--config", help="read limits and baseline path from this config")
    b = sub.add_parser("bless", help="accept current metrics as the new baseline")
    b.add_argument("--current", required=True)
    b.add_argument("--baseline", required=True)
    r = sub.add_parser("run", help="measure then check")
    r.add_argument("--config", required=True)
    r.add_argument("--bless", action="store_true")
    r.add_argument("--screenshots")
    a = ap.parse_args(argv)

    try:
        if a.cmd == "bless":
            cur = load_json(a.current)
            _write_json(a.baseline, cur.get("metrics", cur))
            print(f"blessed -> {a.baseline}. Record why in design/decisions/ before committing it.")
            return 0

        if a.cmd == "check":
            cur = load_json(a.current)
            cur = cur.get("metrics", cur)
            limits, base_path = {}, a.baseline
            if a.config:
                cfg = load_json(a.config)
                limits = cfg.get("limits") or {}
                base_path = base_path or cfg.get("baseline")
            baseline = None
            if base_path and os.path.exists(base_path):
                baseline = load_json(base_path)
            elif base_path:
                print(f"note: no baseline at {base_path}; checking hard limits only. Run bless to create one.")
            return _print_result(*gate(cur, baseline, limits))

        cfg = validate_config(load_json(a.config))
        if not is_local_target(cfg["base_url"]) and not cfg.get("allow_remote"):
            print(f"refusing non-local target {cfg['base_url']}: flows may write data. "
                  "Point base_url at a local server, or set allow_remote only for a read-only target.",
                  file=sys.stderr)
            return 3
        try:
            metrics, details = measure(cfg, getattr(a, "screenshots", None) or cfg.get("screenshots_dir"))
        except ConfigError:
            raise
        except Exception as e:  # app not running, setup step failed, browser missing
            first = (str(e).strip().splitlines() or [type(e).__name__])[0]
            raise ConfigError(f"measurement failed before any metric was taken: {first[:300]}. "
                              f"Is the app running at {cfg['base_url']}? Do setup_steps match the page?")
        payload = {"metrics": metrics, "details": details}

        if a.cmd == "measure":
            text = json.dumps(payload, indent=2, sort_keys=True)
            if a.out == "-":
                print(text)
            else:
                _write_json(a.out, payload)
                print(f"wrote {a.out}")
            return 0

        # run
        print("measured:", json.dumps(metrics, indent=2, sort_keys=True))
        base_path = cfg.get("baseline", "design/design-baseline.json")
        if a.bless:
            _write_json(base_path, metrics)
            print(f"blessed -> {base_path}. Record why in design/decisions/ before committing it.")
            return 0
        baseline = load_json(base_path) if os.path.exists(base_path) else None
        if baseline is None:
            print(f"note: no baseline at {base_path}; checking hard limits only. Run with --bless to create one.")
        fails, notes = gate(metrics, baseline, cfg.get("limits") or {})
        for key, d in sorted(details.items()):
            if d.get("error"):
                notes.append(f"{key}: {d['error']}")
        return _print_result(fails, notes)
    except ConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
