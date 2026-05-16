"""Design tokens — single source of truth for color/spacing/type.

Nothing renders here. Every component imports tokens via CSS variables.
If you find yourself adding a hardcoded color or spacing in a component
file, add it to TOKENS_CSS here instead.
"""
from __future__ import annotations


TOKENS_CSS = """
<style>
:root {
    /* Neutrals */
    --c-bg: #f6f7f9;
    --c-surface: #ffffff;
    --c-border: #e5e7eb;
    --c-border-soft: #eef0f3;
    --c-text: #0f172a;
    --c-text-2: #475569;
    --c-muted: #64748b;
    /* Accent (single) */
    --c-accent: #0369a1;
    --c-accent-soft: #e0f2fe;
    /* Verdict palette (ONLY on verdict semantics) */
    --c-green: #16a34a;
    --c-green-soft: #dcfce7;
    --c-yellow: #ca8a04;
    --c-yellow-soft: #fef9c3;
    --c-red: #dc2626;
    --c-red-soft: #fee2e2;
    /* Spacing scale — 4pt grid */
    --s-1: 4px;
    --s-2: 8px;
    --s-3: 12px;
    --s-4: 16px;
    --s-6: 24px;
    --s-8: 32px;
    /* Radii */
    --r-sm: 6px;
    --r-md: 10px;
    --r-pill: 999px;
    /* Shadows — Linear-style layered: subtle outer ring + soft drop */
    --shadow-card:
        0 0 0 1px rgba(15,23,42,0.04),
        0 1px 2px rgba(15,23,42,0.04),
        0 4px 10px -2px rgba(15,23,42,0.04);
    --shadow-hover:
        0 0 0 1px rgba(3,105,161,0.18),
        0 2px 4px rgba(15,23,42,0.04),
        0 8px 20px -4px rgba(15,23,42,0.08);
    /* Font */
    --font-stack: -apple-system, BlinkMacSystemFont, "Segoe UI",
                  Roboto, "Helvetica Neue", Arial, sans-serif;
}
</style>
"""
