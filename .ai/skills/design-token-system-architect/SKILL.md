---
name: design-token-system-architect
description: >
  Designs and generates complete design token systems: CSS custom properties, semantic token
  layers, Tailwind CSS configuration, dark mode strategy, and component-level token application.
  Use this skill whenever a user wants to build a design system, define color palettes, set up
  spacing scales, configure Tailwind tokens, establish typography scales, implement dark mode
  correctly, or asks "design a token system for my app", "set up Tailwind with custom tokens",
  "how do I implement dark mode properly", "create a color palette", "define spacing scale",
  "design system tokens for fintech / SaaS / dashboard", "how do I use CSS variables with
  Tailwind", or "set up shadcn/ui tokens". Always use this skill for design token work —
  don't hand-craft token systems without it; consistency and semantic layering are easy to
  get wrong.
---

# Design Token System Architect

Design and generate production-grade token systems: a layered architecture of primitive →
semantic → component tokens that scales across themes, surfaces, and breakpoints.

## Token Architecture (Three Layers)

```
Layer 1: Primitive Tokens    ← raw values, never used in components directly
         zinc-900: #18181b
         blue-600: #2563eb

Layer 2: Semantic Tokens     ← intent-based aliases of primitives
         color-text-primary: var(--zinc-900)
         color-accent: var(--blue-600)

Layer 3: Component Tokens    ← scoped to a component, aliases of semantic tokens
         button-bg: var(--color-accent)
         button-text: var(--color-text-on-accent)
```

**Rule**: Components reference Layer 3. Layer 3 references Layer 2. Layer 2 references Layer 1.
Never skip layers. Never hard-code a hex value in a component.

## Protocol

### Step 1 — Intake

Identify:
- **Brand personality**: minimal/technical, warm/consumer, authoritative/fintech, playful?
- **Surfaces**: light only, dark only, or both?
- **Framework**: Tailwind CSS (v3 or v4), plain CSS, CSS-in-JS?
- **Existing constraints**: brand color, existing palette, shadcn/ui?

If none specified, default to: **Tailwind v3 + CSS custom properties + light/dark mode**.

### Step 2 — Generate Primitive Tokens

Generate a curated, harmonious color palette using an OKLCH-based approach for perceptual
uniformity across light and dark modes:

```css
/* primitives.css — NEVER imported in components directly */
:root {
  /* ─── Neutral Scale ─────────────────────────────────── */
  --neutral-0:   #ffffff;
  --neutral-50:  #fafafa;
  --neutral-100: #f4f4f5;
  --neutral-200: #e4e4e7;
  --neutral-300: #d4d4d8;
  --neutral-400: #a1a1aa;
  --neutral-500: #71717a;
  --neutral-600: #52525b;
  --neutral-700: #3f3f46;
  --neutral-800: #27272a;
  --neutral-900: #18181b;
  --neutral-950: #09090b;

  /* ─── Accent (brand-specific, replace hex) ──────────── */
  --accent-50:  #eff6ff;
  --accent-100: #dbeafe;
  --accent-200: #bfdbfe;
  --accent-400: #60a5fa;
  --accent-500: #3b82f6;
  --accent-600: #2563eb;
  --accent-700: #1d4ed8;
  --accent-900: #1e3a8a;

  /* ─── Status ────────────────────────────────────────── */
  --green-500:  #22c55e;  --green-100:  #dcfce7;
  --yellow-500: #eab308;  --yellow-100: #fef9c3;
  --red-500:    #ef4444;  --red-100:    #fee2e2;
  --orange-500: #f97316;  --orange-100: #ffedd5;
}
```

### Step 3 — Generate Semantic Tokens (Light + Dark)

```css
/* tokens.css — imported in app root */

/* ─── Light Mode (default) ──────────────────────────────── */
:root {
  /* Text */
  --color-text-primary:    var(--neutral-900);
  --color-text-secondary:  var(--neutral-600);
  --color-text-tertiary:   var(--neutral-400);
  --color-text-disabled:   var(--neutral-300);
  --color-text-on-accent:  var(--neutral-0);
  --color-text-on-status:  var(--neutral-0);
  --color-text-link:       var(--accent-600);
  --color-text-link-hover: var(--accent-700);
  --color-text-destructive: var(--red-500);

  /* Surfaces */
  --color-surface-base:    var(--neutral-0);
  --color-surface-raised:  var(--neutral-50);
  --color-surface-overlay: var(--neutral-100);
  --color-surface-sunken:  var(--neutral-100);
  --color-surface-accent:  var(--accent-600);

  /* Borders */
  --color-border:          var(--neutral-200);
  --color-border-strong:   var(--neutral-300);
  --color-border-focus:    var(--accent-500);
  --color-border-error:    var(--red-500);

  /* Status surfaces */
  --color-surface-success:     var(--green-100);
  --color-surface-warning:     var(--yellow-100);
  --color-surface-error:       var(--red-100);
  --color-surface-info:        var(--accent-50);

  /* Interactive */
  --color-interactive:         var(--accent-600);
  --color-interactive-hover:   var(--accent-700);
  --color-interactive-pressed: var(--accent-900);
  --color-interactive-muted:   var(--accent-100);

  /* Spacing scale (8px base) */
  --space-px: 1px;
  --space-0:  0;
  --space-1:  4px;
  --space-2:  8px;
  --space-3:  12px;
  --space-4:  16px;
  --space-5:  20px;
  --space-6:  24px;
  --space-8:  32px;
  --space-10: 40px;
  --space-12: 48px;
  --space-16: 64px;
  --space-20: 80px;
  --space-24: 96px;

  /* Typography */
  --font-sans:  'Inter', system-ui, -apple-system, sans-serif;
  --font-mono:  'JetBrains Mono', 'Fira Code', monospace;

  --text-xs:   0.75rem;  --leading-xs:  1rem;
  --text-sm:   0.875rem; --leading-sm:  1.25rem;
  --text-base: 1rem;     --leading-base: 1.5rem;
  --text-lg:   1.125rem; --leading-lg:  1.75rem;
  --text-xl:   1.25rem;  --leading-xl:  1.75rem;
  --text-2xl:  1.5rem;   --leading-2xl: 2rem;
  --text-3xl:  1.875rem; --leading-3xl: 2.25rem;
  --text-4xl:  2.25rem;  --leading-4xl: 2.5rem;

  --font-normal:   400;
  --font-medium:   500;
  --font-semibold: 600;
  --font-bold:     700;

  /* Border radius */
  --radius-sm:   0.25rem;   /* 4px  */
  --radius-md:   0.375rem;  /* 6px  */
  --radius-lg:   0.5rem;    /* 8px  */
  --radius-xl:   0.75rem;   /* 12px */
  --radius-2xl:  1rem;      /* 16px */
  --radius-full: 9999px;

  /* Shadows */
  --shadow-sm:  0 1px 2px 0 rgb(0 0 0 / 0.05);
  --shadow-md:  0 4px 6px -1px rgb(0 0 0 / 0.1), 0 2px 4px -2px rgb(0 0 0 / 0.1);
  --shadow-lg:  0 10px 15px -3px rgb(0 0 0 / 0.1), 0 4px 6px -4px rgb(0 0 0 / 0.1);
  --shadow-xl:  0 20px 25px -5px rgb(0 0 0 / 0.1), 0 8px 10px -6px rgb(0 0 0 / 0.1);

  /* Motion */
  --duration-fast:   100ms;
  --duration-normal: 200ms;
  --duration-slow:   300ms;
  --ease-out: cubic-bezier(0.0, 0.0, 0.2, 1.0);
  --ease-in:  cubic-bezier(0.4, 0.0, 1.0, 1.0);
  --ease-inout: cubic-bezier(0.4, 0.0, 0.2, 1.0);
  --ease-spring: cubic-bezier(0.34, 1.56, 0.64, 1.0);
}

/* ─── Dark Mode ─────────────────────────────────────────── */
[data-theme="dark"], .dark {
  /* Text */
  --color-text-primary:    var(--neutral-50);
  --color-text-secondary:  var(--neutral-400);
  --color-text-tertiary:   var(--neutral-500);
  --color-text-disabled:   var(--neutral-700);
  --color-text-link:       var(--accent-400);
  --color-text-link-hover: var(--accent-200);
  --color-text-destructive: var(--red-500);

  /* Surfaces */
  --color-surface-base:    var(--neutral-950);
  --color-surface-raised:  var(--neutral-900);
  --color-surface-overlay: var(--neutral-800);
  --color-surface-sunken:  #0a0a0a;
  --color-surface-accent:  var(--accent-600);

  /* Borders */
  --color-border:          var(--neutral-800);
  --color-border-strong:   var(--neutral-700);
  --color-border-focus:    var(--accent-400);

  /* Interactive */
  --color-interactive:         var(--accent-500);
  --color-interactive-hover:   var(--accent-400);
  --color-interactive-pressed: var(--accent-600);
  --color-interactive-muted:   rgb(59 130 246 / 0.15);

  /* Shadows (elevated in dark mode for depth) */
  --shadow-sm:  0 1px 2px 0 rgb(0 0 0 / 0.3);
  --shadow-md:  0 4px 6px -1px rgb(0 0 0 / 0.4), 0 2px 4px -2px rgb(0 0 0 / 0.3);
  --shadow-lg:  0 10px 15px -3px rgb(0 0 0 / 0.5), 0 4px 6px -4px rgb(0 0 0 / 0.4);
}
```

### Step 4 — Tailwind v3 Configuration

```typescript
// tailwind.config.ts
import type { Config } from 'tailwindcss'

const config: Config = {
  content: [
    './src/**/*.{ts,tsx}',
    './components/**/*.{ts,tsx}',
  ],
  darkMode: ['class', '[data-theme="dark"]'],
  theme: {
    // ─── Override defaults with token references ──────────
    colors: {
      transparent: 'transparent',
      current: 'currentColor',
      // Expose CSS variables as Tailwind colors
      text: {
        primary:     'var(--color-text-primary)',
        secondary:   'var(--color-text-secondary)',
        tertiary:    'var(--color-text-tertiary)',
        disabled:    'var(--color-text-disabled)',
        'on-accent': 'var(--color-text-on-accent)',
        link:        'var(--color-text-link)',
        destructive: 'var(--color-text-destructive)',
      },
      surface: {
        base:    'var(--color-surface-base)',
        raised:  'var(--color-surface-raised)',
        overlay: 'var(--color-surface-overlay)',
        sunken:  'var(--color-surface-sunken)',
        accent:  'var(--color-surface-accent)',
      },
      border: {
        DEFAULT: 'var(--color-border)',
        strong:  'var(--color-border-strong)',
        focus:   'var(--color-border-focus)',
        error:   'var(--color-border-error)',
      },
      interactive: {
        DEFAULT:  'var(--color-interactive)',
        hover:    'var(--color-interactive-hover)',
        pressed:  'var(--color-interactive-pressed)',
        muted:    'var(--color-interactive-muted)',
      },
    },
    spacing: {
      px: '1px', '0': '0',
      '1': '4px', '2': '8px', '3': '12px', '4': '16px',
      '5': '20px', '6': '24px', '8': '32px', '10': '40px',
      '12': '48px', '16': '64px', '20': '80px', '24': '96px',
    },
    fontFamily: {
      sans: ['var(--font-sans)'],
      mono: ['var(--font-mono)'],
    },
    fontSize: {
      xs:   ['var(--text-xs)',   { lineHeight: 'var(--leading-xs)' }],
      sm:   ['var(--text-sm)',   { lineHeight: 'var(--leading-sm)' }],
      base: ['var(--text-base)', { lineHeight: 'var(--leading-base)' }],
      lg:   ['var(--text-lg)',   { lineHeight: 'var(--leading-lg)' }],
      xl:   ['var(--text-xl)',   { lineHeight: 'var(--leading-xl)' }],
      '2xl':['var(--text-2xl)', { lineHeight: 'var(--leading-2xl)' }],
      '3xl':['var(--text-3xl)', { lineHeight: 'var(--leading-3xl)' }],
      '4xl':['var(--text-4xl)', { lineHeight: 'var(--leading-4xl)' }],
    },
    borderRadius: {
      sm: 'var(--radius-sm)', md: 'var(--radius-md)',
      lg: 'var(--radius-lg)', xl: 'var(--radius-xl)',
      '2xl': 'var(--radius-2xl)', full: 'var(--radius-full)',
    },
    boxShadow: {
      sm: 'var(--shadow-sm)', md: 'var(--shadow-md)',
      lg: 'var(--shadow-lg)', xl: 'var(--shadow-xl)',
      none: 'none',
    },
    transitionDuration: {
      fast: 'var(--duration-fast)',
      DEFAULT: 'var(--duration-normal)',
      slow: 'var(--duration-slow)',
    },
  },
  plugins: [
    require('@tailwindcss/typography'),
    require('@tailwindcss/forms'),
  ],
}

export default config
```

### Step 5 — shadcn/ui Token Mapping

If using shadcn/ui, map the generated tokens to its expected CSS variable names in `globals.css`:

```css
@layer base {
  :root {
    --background:       var(--color-surface-base);
    --foreground:       var(--color-text-primary);
    --card:             var(--color-surface-raised);
    --card-foreground:  var(--color-text-primary);
    --popover:          var(--color-surface-overlay);
    --popover-foreground: var(--color-text-primary);
    --primary:          var(--color-interactive);
    --primary-foreground: var(--color-text-on-accent);
    --secondary:        var(--color-surface-overlay);
    --secondary-foreground: var(--color-text-primary);
    --muted:            var(--color-surface-sunken);
    --muted-foreground: var(--color-text-secondary);
    --accent:           var(--color-interactive-muted);
    --accent-foreground: var(--color-text-link);
    --destructive:      var(--red-500);
    --destructive-foreground: var(--neutral-0);
    --border:           var(--color-border);
    --input:            var(--color-border);
    --ring:             var(--color-border-focus);
    --radius:           var(--radius-md);
  }
}
```

### Step 6 — Dark Mode Implementation Strategy

**Preferred approach**: `data-theme` attribute on `<html>` (not `prefers-color-scheme` alone):

```typescript
// app/layout.tsx
import { cookies } from 'next/headers'

export default function RootLayout({ children }) {
  const theme = cookies().get('theme')?.value ?? 'light'
  return (
    <html data-theme={theme} lang="en">
      {children}
    </html>
  )
}

// hooks/useTheme.ts
export function useTheme() {
  const toggle = () => {
    const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark'
    document.documentElement.dataset.theme = next
    document.cookie = `theme=${next}; path=/; max-age=31536000`
  }
  return { toggle }
}
```

**Why not `prefers-color-scheme` alone**: Server can't read it → causes flash of incorrect
theme on SSR. The `data-theme` approach reads a cookie on the server, rendering the correct
theme immediately with no flash.

## Quality Gates

- [ ] No hex values in component styles (only `var(--token-name)` or Tailwind semantic classes)
- [ ] Dark mode has been applied to ALL six semantic categories (text, surface, border, status, interactive, shadow)
- [ ] Contrast ratios checked: text-primary on surface-base ≥ 7:1 (AAA), text-secondary ≥ 4.5:1 (AA)
- [ ] `prefers-reduced-motion` respected in motion tokens (use `@media (prefers-reduced-motion: reduce)`)
- [ ] shadcn/ui components receive tokens through the mapping, not direct overrides
- [ ] Token file is separate from component styles (primitives.css → tokens.css → components)

## Activation Triggers

- "Design a token system for my app"
- "Set up Tailwind with custom tokens / design tokens"
- "How do I implement dark mode correctly in Next.js?"
- "Create a color palette / spacing scale / typography scale"
- "Set up shadcn/ui tokens / theme"
- "How do I use CSS variables with Tailwind?"
- "Design system for fintech / SaaS / dashboard"
- "My dark mode has a flash / flicker on load"

## Skill Chain

**Feeds into**: `accessibility-system-architect` (the token system gives contrast and focus-state checks a reference baseline to measure against) → `component-quality-gate` (components are checked against the token system) → `motion-interaction-architect` (motion tokens are a natural extension of the design token system).

**Creative combination**: Design tokens → motion tokens → component audit forms a complete "design system in a day" chain. Run `design-token-system-architect` to establish the palette, `motion-interaction-architect` to extend it with animation tokens, then `component-quality-gate` on every component to enforce compliance.

## Creative Combinations

**The "Cross-Platform Token" pattern**: Generate tokens with `design-token-system-architect` as CSS custom properties for web, then have `react-native-expo-architect` convert them to a `tokens.ts` file for Expo's `StyleSheet`. One source of truth, two platforms, zero drift.

**The "Dark Mode First" pattern**: Run `design-token-system-architect` with dark mode as the primary surface (not an afterthought), then `accessibility-system-architect` to verify contrast ratios in both modes, then `testing-strategy-architect` to add theme-switching tests. Dark mode that's designed in, not bolted on.
