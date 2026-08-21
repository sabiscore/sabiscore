---
name: component-quality-gate
description: >
  Runs a comprehensive quality gate on frontend components covering accessibility (WCAG AA),
  performance (Core Web Vitals impact), testability, Storybook story generation, and TypeScript
  prop contract correctness. Use this skill whenever a user wants to review a React or Next.js
  component for production readiness, add accessibility to a component, write tests for a
  component, generate Storybook stories, optimize a component for performance, check prop types,
  or asks "is this component production-ready", "audit this component for accessibility",
  "write tests for this component", "generate Storybook stories", "optimize this component",
  "check my component props / types", or pastes a React/TSX component and asks for a review.
  Always use this skill for component-level review — it catches subtle issues that general
  code review misses.
---

# Component Quality Gate

Audit any React/Next.js component against six production-readiness dimensions. Output is
always actionable: specific issues, specific fixes, and corrected code.

## Protocol

### Step 1 — Intake

Accept any of: pasted TSX/JSX component, a GitHub file link, a Storybook story, or a
written description of the component. If code is provided, audit both the TypeScript
contract and the inferred visual output across all six dimensions below.

Ask only if needed: **"Do you want corrected code, tests, Storybook stories, or all three?"**
Default: produce all three for every audit.

## Six Quality Dimensions

### 1. TypeScript Contract
- Props interface is explicit (no `any`, no implicit `{[key: string]: unknown}`)
- Required vs optional props correctly modeled
- Event handlers typed with correct React event type (`React.MouseEvent<HTMLButtonElement>`)
- `children` typed as `React.ReactNode` (not `JSX.Element` — too restrictive)
- `ref` forwarded with `forwardRef` when DOM access is needed by consumers
- `displayName` set on memoized/forwarded components for DevTools readability

### 2. Accessibility (WCAG AA)
- Interactive elements (`button`, `a`, `input`) have accessible names:
  - Visible label, or `aria-label`, or `aria-labelledby`
  - Never an empty button with only an icon (must have `aria-label` or `<span className="sr-only">`)
- Color is not the sole information carrier (icons + color, not color alone)
- Focus is visible: `focus-visible:ring-2` not suppressed with `outline: none` alone
- Keyboard interactions correct:
  - `<button>` for actions, `<a>` for navigation (never `<div onClick>` for either)
  - `Enter` and `Space` both trigger `<button>` click (native behavior — don't override)
  - Custom dropdowns/modals implement correct ARIA pattern (see below)
- Images: `<img alt="...">` — decorative images use `alt=""` explicitly
- Touch targets: minimum 44×44px for all interactive elements
- `aria-disabled` used instead of HTML `disabled` when element must remain in tab order

**ARIA patterns for custom widgets:**
```tsx
// Disclosure (accordion)
<button aria-expanded={isOpen} aria-controls="panel-id">Toggle</button>
<div id="panel-id" role="region" aria-labelledby="button-id">{content}</div>

// Dialog/Modal
<div role="dialog" aria-modal="true" aria-labelledby="dialog-title">
  <h2 id="dialog-title">Title</h2>
</div>
// Focus must be trapped inside dialog while open — use @radix-ui/react-dialog

// Combobox
<input role="combobox" aria-expanded={open} aria-autocomplete="list"
       aria-controls="listbox-id" aria-activedescendant={activeId} />
<ul id="listbox-id" role="listbox">
  <li role="option" aria-selected={selected} id="option-1">Item</li>
</ul>
```

### 3. Performance
- No inline object/array creation in JSX props (creates new reference every render):
  ```tsx
  // ❌ Creates new object every render
  <Component style={{ padding: 16 }} />
  // ✅ Stable reference
  const STYLE = { padding: 16 } // outside component
  <Component style={STYLE} />
  ```
- `React.memo` applied to components that receive stable props and re-render often
- `useCallback` wrapping event handlers passed to memoized children
- `useMemo` for expensive computations (not for trivial ones — adds overhead)
- Images use `next/image` with `width`, `height`, and `priority` on above-fold images
- No synchronous data fetching in render (use RSC, `Suspense`, or `use()` hook)
- Lazy loading for components not needed on initial render: `const Modal = lazy(() => import('./Modal'))`
- `loading="lazy"` on below-fold images

### 4. Testing
Every component should have:
- **Unit test**: renders without crashing, key props render correctly
- **Interaction test**: user events (click, type, select) produce expected state changes
- **Accessibility test**: `axe-core` scan finds no violations

**Test template (Vitest + Testing Library + axe):**
```tsx
import { render, screen, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { axe, toHaveNoViolations } from 'jest-axe'
import { ComponentName } from './ComponentName'

expect.extend(toHaveNoViolations)

describe('ComponentName', () => {
  it('renders with required props', () => {
    render(<ComponentName label="Test" />)
    expect(screen.getByText('Test')).toBeInTheDocument()
  })

  it('handles user interaction correctly', async () => {
    const onAction = vi.fn()
    const user = userEvent.setup()
    render(<ComponentName onAction={onAction} />)
    await user.click(screen.getByRole('button', { name: /submit/i }))
    expect(onAction).toHaveBeenCalledTimes(1)
  })

  it('has no accessibility violations', async () => {
    const { container } = render(<ComponentName label="Test" />)
    const results = await axe(container)
    expect(results).toHaveNoViolations()
  })

  it('is keyboard navigable', async () => {
    const user = userEvent.setup()
    render(<ComponentName />)
    await user.tab()
    expect(screen.getByRole('button')).toHaveFocus()
  })
})
```

### 5. Storybook Stories
Generate a complete story file for every component:

```tsx
// ComponentName.stories.tsx
import type { Meta, StoryObj } from '@storybook/react'
import { ComponentName } from './ComponentName'

const meta: Meta<typeof ComponentName> = {
  title: 'Components/Category/ComponentName',
  component: ComponentName,
  tags: ['autodocs'],
  parameters: {
    layout: 'centered',
    a11y: { config: { rules: [{ id: 'color-contrast', enabled: true }] } },
  },
  argTypes: {
    variant: {
      control: 'select',
      options: ['primary', 'secondary', 'destructive'],
    },
    disabled: { control: 'boolean' },
    onClick: { action: 'clicked' },
  },
}

export default meta
type Story = StoryObj<typeof meta>

export const Default: Story = {
  args: { label: 'Button', variant: 'primary' },
}

export const Secondary: Story = {
  args: { label: 'Button', variant: 'secondary' },
}

export const Destructive: Story = {
  args: { label: 'Delete', variant: 'destructive' },
}

export const Disabled: Story = {
  args: { label: 'Button', disabled: true },
}

// Loading state (if applicable)
export const Loading: Story = {
  args: { label: 'Saving...', isLoading: true },
}
```

### 6. Error & Loading States
Every data-dependent component must explicitly handle:
- **Loading**: skeleton, spinner, or placeholder (never blank)
- **Error**: user-readable message + retry action (never a raw error object in the UI)
- **Empty**: intentional empty state design (never a blank list)

```tsx
// Pattern: explicit state machine, not boolean flags
type ComponentState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'error'; message: string; retry: () => void }
  | { status: 'success'; data: Data }
```

## Audit Report Format

```
## Component Quality Gate: [ComponentName]

### TypeScript Contract
[Pass | Issues found]
- [Issue] → [Fix]

### Accessibility
[Pass | Issues found]
- [Issue] → [Fix]

### Performance
[Pass | Issues found]
- [Issue] → [Fix]

### Testing Coverage
[Exists / Missing]
- [What's tested] / [What needs tests]

### Storybook
[Exists / Missing stories]
- [Stories present] / [Stories to add]

### Error & Loading States
[Handled / Missing]
- [States handled] / [States missing]

### Overall: [Production Ready | Needs Work | Blocked]
```

## Corrected Component Output

After the audit, always produce the corrected component with:
- All critical issues resolved inline
- `// ← [reason]` comment on every changed line
- Separate test file with `describe('ComponentName', () => {...})`
- Separate story file

## Quality Gates (what Production Ready means)

- [ ] No TypeScript errors or `any` in props
- [ ] All interactive elements have accessible names
- [ ] Focus ring visible in `:focus-visible` state
- [ ] `axe` scan returns zero violations
- [ ] At least 3 tests: render, interaction, a11y
- [ ] Storybook story covers at least: Default, Disabled, and one variant
- [ ] Loading and error states both have explicit UI

## Activation Triggers

- "Is this component production-ready?"
- "Audit this component for accessibility"
- "Write tests for this component"
- "Generate Storybook stories for [component]"
- "Review my React / TSX component"
- "Optimize this component's performance"
- "Check my component props / TypeScript types"
- "My component has accessibility issues"

## Skill Chain

**Feeds into**: `testing-strategy-architect` (test templates from the gate feed directly into the test suite) → `frontend-product-design-architect` (visual findings loop back for design correction).

**Creative combination**: Pair with `design-token-system-architect` and `motion-interaction-architect` for a complete component lifecycle — tokens define the palette, motion defines the behaviour, the quality gate validates both.
