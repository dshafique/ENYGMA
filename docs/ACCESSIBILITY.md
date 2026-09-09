# What the design system does not do

Measured 2026-09-09 against Mk II.46. Nothing here was fixed, on purpose: the
achromatic system is deliberate and these three findings all cost something
visible to repair. This file exists so the decision is a decision and not an
oversight, and so the numbers do not have to be re-derived to revisit it.

The prompt was "does Apple's Human Interface Guidelines help us". Mostly no.
The HIG pages are JavaScript-rendered and cannot be read by a fetch, and the
half that is readable is iOS-specific -- 44pt targets, SF Symbols, the iOS
navigation model, sheet grabbers. ENYGMA is an Android WebView in a Capacitor
shell. Grafting iOS conventions onto it would make it worse, not better. What
follows comes instead from WCAG 2.2 and Material 3, which are platform-neutral,
and every number was taken from `src/static/css/` rather than from a document.

## 1. Control edges do not meet 3.0

Text is fine. Every foreground/background pair in the stylesheet passes WCAG AA
in both themes: light runs 16.43 down to 6.19, dark 15.87 down to 4.67. There is
no contrast problem with anything anybody reads.

The boundaries of controls are a separate requirement (WCAG 1.4.11, 3.0:1) and
both border tokens miss it in both themes:

| token             | on `--bg` light | on `--bg` dark |
| ----------------- | --------------- | -------------- |
| `--border-rest`   | 1.41            | 1.55           |
| `--border-strong` | 2.50            | 2.21           |

`--border-strong` missing is the surprising part -- the token named for being the
visible one is not visible enough either.

It is a soft failure rather than a hard one wherever the control also carries a
text label that passes, because then the edge is not the only thing identifying
the control. It is a real failure on the outlined buttons, the filter chips and
the dashed edge on Nobody's cards, where the edge is doing the work alone.

Fixing it means darkening the tokens, which makes the whole interface look more
drawn and less airy. That is the cost, and it is why this is unfixed.

## 2. Eight controls are below the touch floor

44pt (Apple) / 48dp (Material). Heights as built:

    .modelpick      26px
    .statepick      28px
    .filters .chip  30px
    .saveas-pick    30px
    .btn.sm         34px
    .chip           34px
    .filesbtn       34px
    .iconbtn        38px

`.btn.wide` at 56px is fine. `.recbtn .dot` at 9px is decorative and not a
target.

This one *can* be fixed invisibly, which makes it the odd one out: an `::after`
pseudo-element extending the hit area past the visual box leaves every size,
spacing and density exactly as it is and only grows the region that responds to
a tap. If any of the three is ever revisited, start here -- it costs nothing.

The worst of them in practice is `.modelpick` at 26px, tapped on a phone.

## 3. The app ignores the system font size

103 font-size declarations in `app.css`. All 103 are in `px`. None are in `rem`
or `em`. If the phone is set to larger text, every other app on it responds and
ENYGMA does not.

Converting them is mechanical. Making it *work* is not: the layout is built on
fixed pixel tokens -- `--rail: 72px`, `--pane: 336px`, `--tabbar: 60px`,
`--player: 72px` -- and at 150% or 200% scale the text would fight them. This
needs the scale actually tested on hardware, not a find-and-replace, which is
why it is the largest of the three jobs and the one most likely to need a second
pass.

## What is already right

Not everything here is a defect. Recorded so a future audit does not re-open
settled ground:

- Reduced motion is handled: 8 animations, 4 `prefers-reduced-motion` blocks.
- Both themes are real, defined as token overrides rather than filters, and both
  pass text contrast independently.
- `[hidden] { display: none !important; }` is global, which is an accessibility
  property and not only a layout one -- a hidden element that a class re-shows is
  still in the accessibility tree.
