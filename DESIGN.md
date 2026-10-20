---
name: Road Ready TN
description: A calm night-route study app for the Tennessee driver knowledge test.
colors:
  night-map: "#0d1317"
  map-grid: "#151e25"
  map-road: "#19242c"
  map-water: "#0c1924"
  sheet: "#172027"
  sheet-raised: "#1f2a33"
  sheet-edge: "#26323c"
  hairline: "#2a3640"
  control-line: "#3a4753"
  ink: "#eef2f5"
  muted: "#9babb8"
  banner-blue: "#1a58c2"
  banner-blue-top: "#2467d8"
  banner-ink: "#ffffff"
  banner-button-ink: "#0e3a85"
  route-blue: "#4c98ff"
  route-casing: "#0f2f63"
  route-gain: "#a9cdff"
  route-ink: "#071a36"
  route-soft: "#16263d"
  correct-green: "#5fd08a"
  correct-ink: "#0c1f13"
  correct-soft: "#16291f"
  incorrect-coral: "#f27c6b"
  incorrect-ink: "#2a0f0b"
  incorrect-soft: "#33201e"
  focus-amber: "#ffd479"
  scene-ground: "#111920"
  road: "#28333c"
  road-edge: "#a3b0bb"
  lane-yellow: "#e7b442"
  lane-white: "#e6e9ec"
  car-light: "#a3aeb8"
  car-dark: "#687480"
  glass: "#22303b"
typography:
  display-banner:
    fontFamily: "Atkinson Hyperlegible Next, Verdana, system-ui, sans-serif"
    fontSize: "clamp(38px, 10.4vw, 46px)"
    fontWeight: 800
    lineHeight: 1.08
    letterSpacing: "-0.03em"
  display:
    fontFamily: "Atkinson Hyperlegible Next, Verdana, system-ui, sans-serif"
    fontSize: "clamp(34px, 9vw, 44px)"
    fontWeight: 800
    lineHeight: 1.08
    letterSpacing: "-0.03em"
  headline:
    fontFamily: "Atkinson Hyperlegible Next, Verdana, system-ui, sans-serif"
    fontSize: "clamp(24px, 6vw, 30px)"
    fontWeight: 800
    lineHeight: 1.08
    letterSpacing: "-0.02em"
  result:
    fontFamily: "Atkinson Hyperlegible Next, Verdana, system-ui, sans-serif"
    fontSize: "clamp(22px, 5.4vw, 28px)"
    fontWeight: 800
    lineHeight: 1.2
    letterSpacing: "-0.02em"
  title:
    fontFamily: "Atkinson Hyperlegible Next, Verdana, system-ui, sans-serif"
    fontSize: "clamp(21px, 5vw, 24px)"
    fontWeight: 700
    lineHeight: 1.36
    letterSpacing: "-0.005em"
  body:
    fontFamily: "Atkinson Hyperlegible Next, Verdana, system-ui, sans-serif"
    fontSize: "18px"
    fontWeight: 400
    lineHeight: 1.5
  button:
    fontFamily: "Atkinson Hyperlegible Next, Verdana, system-ui, sans-serif"
    fontSize: "19px"
    fontWeight: 800
    letterSpacing: "-0.005em"
  label:
    fontFamily: "Atkinson Hyperlegible Next, Verdana, system-ui, sans-serif"
    fontSize: "15px"
    fontWeight: 700
rounded:
  seg: "3px"
  key: "8px"
  tile: "12px"
  field: "14px"
  control: "16px"
  scene: "20px"
  card: "22px"
  banner: "26px"
  sheet: "28px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "14px"
  lg: "18px"
  xl: "22px"
components:
  button-primary:
    backgroundColor: "{colors.banner-blue}"
    textColor: "{colors.banner-ink}"
    typography: "{typography.button}"
    rounded: "{rounded.control}"
    padding: "16px 18px"
    height: "58px"
  button-on-banner:
    backgroundColor: "{colors.banner-ink}"
    textColor: "{colors.banner-button-ink}"
    typography: "{typography.button}"
    rounded: "{rounded.control}"
    padding: "16px 18px"
    height: "58px"
  button-quiet:
    backgroundColor: "{colors.sheet-raised}"
    textColor: "{colors.ink}"
    typography: "{typography.button}"
    rounded: "{rounded.control}"
    padding: "16px 18px"
    height: "58px"
  button-slim:
    backgroundColor: "{colors.sheet-raised}"
    textColor: "{colors.ink}"
    rounded: "{rounded.tile}"
    padding: "10px 14px"
    height: "44px"
  link-quiet:
    textColor: "{colors.muted}"
    padding: "10px 8px"
    height: "44px"
  maneuver-banner:
    backgroundColor: "{colors.banner-blue}"
    textColor: "{colors.banner-ink}"
    rounded: "{rounded.banner}"
    padding: "22px 20px 20px"
  next-card:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
    rounded: "{rounded.card}"
    padding: "18px"
  answer-option:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "14px"
  answer-option-correct:
    backgroundColor: "{colors.correct-soft}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "14px"
  answer-option-rest:
    textColor: "{colors.muted}"
    rounded: "{rounded.control}"
    padding: "14px"
  progress-panel:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.muted}"
    rounded: "{rounded.card}"
    padding: "14px 18px 16px"
  input-field:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
    rounded: "{rounded.field}"
    padding: "12px 14px"
    height: "54px"
---

# Design System: Road Ready TN

## Overview

**Creative North Star: "Night Route"**

The app is turn-by-turn navigation driven at night. One maneuver banner in deep route blue says the one thing to do, a dark street map shows how far the Learner has come, and slate sheets hold everything else. The ground is a blue-black night map; panels are slate sheets marked by hairline inner edges rather than borders or heavy shadows. Route blue belongs to the Learner: his place on the map, his car's outline in a drawing, his path drawn as a cased route line, the segment of the quiz he is on.

Density is low and the hierarchy is single-file: one column, at most 640px wide, with each screen holding one heavy element (the banner, the question, the result) and everything else stepped down in weight and color. State is carried by form as well as hue so it reads without color: learned road is a solid line, road still ahead is a broken line, the current question is a broken segment, a correct pick wears a filled key and a check, a wrong pick a ring and a cross.

The world is dark on every device, with no light theme. It is calm by construction: no timers, no celebration effects, motion only to settle new things into place, and all of it gated on reduced-motion preference.

**Key Characteristics:**
- Blue-black night map ground with a faint street grid, water and two arterials, all within a few steps of the ground.
- One maneuver banner per home screen: a deep blue gradient slab with a white full-width button.
- Slate sheets with 1px inner hairlines; depth comes from tone, not borders.
- Route blue marks the Learner and only the Learner; green and coral mark only results.
- One family, Atkinson Hyperlegible Next, from 400 body to 800 headings and buttons.
- Large, soft corners (16 to 28px) on every container and control.

## Colors

A near-monochrome blue-black night with one owned blue, plus two result colors that appear only when an answer has been given.

### Primary
- **Route Blue** (route-blue): the Learner's own marks. The puck, the learned stretch of the route, the cased path line and dashed car outline in drawings, the done segments of the question bar, the hover ring on an answer, selection highlight, caret and checkbox accent. Paired with **Route Casing** (route-casing) as the dark under-stroke of a path, **Route Gain** (route-gain) for the stretch a just-finished quiz added, and **Route Soft** (route-soft) as the fill of a neutral note.
- **Banner Blue** (banner-blue, with banner-blue-top as the top of its gradient): the maneuver banner and the primary button. It is the one loud surface on a screen. **Banner Button Ink** (banner-button-ink) is the text of the white button that sits on the banner.

### Secondary
- **Correct Green** (correct-green): only for a correct answer. The result mark, the correct option's ring, key and tag, the learned tile in the quiz strip, the ring and badge in a drawing. Its ink (correct-ink) sits on it; its soft tone (correct-soft) fills the correct option.
- **Incorrect Coral** (incorrect-coral): only for an incorrect answer. The result mark, the picked-wrong option's ring, key and tag, the cross badge in a drawing. Its ink (incorrect-ink) sits on it.

### Tertiary
- **Focus Amber** (focus-amber): the 3px keyboard focus ring and the focus/hover outline on a tappable object in a drawing. Never decorative.

### Neutral
- **Night Map** (night-map): page ground and map ground; also the theme color.
- **Map Grid, Map Road, Map Water** (map-grid, map-road, map-water): the quiet streets behind the route, a few steps off the ground.
- **Sheet** (sheet): cards, the progress panel, the sheet under the map, answer options, fields.
- **Sheet Raised** (sheet-raised): quiet buttons and inset boxes on a sheet.
- **Sheet Edge** (sheet-edge): the 1px inner hairline on sheets and scenes.
- **Hairline** (hairline): dividers between rows and the resting color of a not-yet-answered question segment.
- **Control Line** (control-line): the 1.5px inner stroke on controls (buttons, options, keys, fields).
- **Ink** (ink): primary text. **Muted** (muted): secondary text, quiet links, the question once it steps back under its result.
- **Scene palette** (scene-ground, road, road-edge, lane-yellow, lane-white, car-light, car-dark, glass): the drawings' road surfaces, real lane colors, neutral cars and glass.

### Named Rules
**The Results-Only Rule.** In the interface, green appears only for a correct answer and coral only for an incorrect one. Drawings are the exception: real signs, signals, lane lines and painted cars keep their real-world colors (a stop sign is red and white), because the world itself is a road.

**The Route Belongs To You Rule.** Route blue marks the Learner's own place, car, path and progress. It never marks someone else's car, a decoration, or a result.

**The One Banner Rule.** Banner blue fills one slab per screen: the maneuver banner on home, or the primary button where there is no banner. A second blue slab competes with the one thing to do.

## Typography

**Display Font:** Atkinson Hyperlegible Next (with Verdana, system-ui, sans-serif)
**Body Font:** Atkinson Hyperlegible Next (same stack)

**Character:** A single legibility-first family carries everything; hierarchy comes from weight (400 body, 700 labels and questions, 800 headings, results and buttons) and size, with tight negative tracking only on headings. It is self-hosted as one variable file.

### Hierarchy
- **Display Banner** (800, clamp(38px, 10.4vw, 46px), 1.08): the heading inside the maneuver banner (Practice quiz, Section N, Practice tests).
- **Display** (800, clamp(34px, 9vw, 44px), 1.08): page headings outside the banner.
- **Headline** (800, clamp(24px, 6vw, 30px), 1.08): sub-headings and scores; drops to 22px on the next card and Helper parts.
- **Result** (800, clamp(22px, 5.4vw, 28px), 1.2): the result line that leads an answered screen, in green or with a coral mark.
- **Title** (700, clamp(21px, 5vw, 24px), 1.36): the question. Once answered it steps back to 18px muted.
- **Body** (400, 18px, 1.5): explanations, options and running text; the lesson's one sentence runs at 19px.
- **Button** (800, 19px): every full-width button; 17px on the next card, 16px on slim buttons.
- **Label** (700, 15px): the app name, option keys, tags, keys under the quiz strip, map labels at 14px.

### Named Rules
**The One Family Rule.** Every word is Atkinson Hyperlegible Next. Hierarchy is weight and size, never a second face.

**The Tabular Count Rule.** Every count (questions learned, question N of M, scores) uses tabular numerals so progress never jitters.

## Layout

A single centered column, max 640px, with 14px gaps between blocks and a 16px minimum gutter that respects safe-area insets (24px top, 48px bottom). On home the blocks lock together like a navigation screen: the dark next card tucks 32px up under the banner, the map pulls 40px up under the card, and the sheet's rounded top rides 26px up over the map. Under 700px wide the map and the sheet run edge to edge, and the sheet runs to the bottom of the screen. The Next button is sticky 16px from the bottom while a question is on screen. Internal padding steps 14, 18, 20, 22px; touch targets are at least 44px and full buttons 58px.

## Elevation & Depth

Tonal layering first: the night map, then slate sheets one step up, then raised boxes one step further, each separated by a 1px inner hairline. Real shadows are soft, dark and deep-offset, used only where one layer slides over another: under the banner, under the next card, under the sheet's top edge, and under the two blue/white primary buttons. Highlights are a 1px white inner line at 16 to 18% on the blue surfaces.

### Shadow Vocabulary
- **Banner lift** (`box-shadow: 0 18px 40px -16px rgb(0 0 0 / .85), inset 0 1px 0 rgb(255 255 255 / .16)`): the maneuver banner.
- **Card tuck** (`box-shadow: inset 0 0 0 1px var(--edge), 0 14px 30px -18px rgb(0 0 0 / .9)`): the next card under the banner.
- **Sheet rise** (`box-shadow: 0 -16px 36px -12px rgb(0 0 0 / .7), inset 0 1px 0 var(--edge)`): the sheet's top edge over the map.
- **Primary press** (`box-shadow: 0 12px 24px -12px rgb(0 0 0 / .8), inset 0 1px 0 rgb(255 255 255 / .18)`): the primary button.
- **Hairline** (`box-shadow: inset 0 0 0 1px var(--edge)`): every resting sheet, panel and scene.

### Named Rules
**The Hairline Not Border Rule.** Containers are edged with a 1px inset hairline, controls with a 1.5px inset control line, and state with a 2px inset ring. Outer borders are not used.

## Shapes

Soft, generous corners throughout, scaled by size: 3px on bar segments, 7 to 8px on keys and mini tiles, 12px on tiles and slim buttons, 14px on fields and notes, 16px on buttons and answer options, 20 to 22px on scenes, cards and panels, 26px on the banner, 28px on the sheet's top. Joined layers square off where they meet (the next card is rounded only at the bottom, the sheet only at the top). Result marks are circles; the app mark and puck are a navigation arrowhead.

## Components

### Buttons
- **Shape:** gently rounded (16px), full width, 58px tall, 800 weight.
- **Primary:** banner blue with white text and the primary press shadow.
- **On the banner:** white with banner-button-ink text, so the banner keeps one blue.
- **Quiet:** sheet-raised with ink text and a 1.5px control-line inner stroke; 52px on the next card.
- **Hover / Active:** brightness 1.08 on hover, 1px press on active, 160ms ease-out. Focus is the 3px amber ring, 3px offset. Disabled is 50% opacity.
- **Slim:** auto width, 44px, 12px radius, 16px text.
- **Link:** muted, underlined in control-line with a 4px offset, 44px tall; brightens to ink on hover.

### Maneuver Banner (signature)
Deep blue vertical gradient (banner-blue-top to banner-blue), 26px corners, 22/20px padding, 14px gap, the display-banner heading and one white full-width button. Text inside runs white at 88%. It always sits on top; the next card tucks under it.

### Night Route Map (signature)
An SVG night map: grid streets, a river and two arterials in map tones; the 120-question route as a cased line (route casing at 60%, 15px), the road ahead a muted broken line (7/7 dash), the learned stretch solid route blue (8px, round caps), a newly gained stretch in route gain drawn in over 1100ms. Eleven short ink ticks mark the Sections; Start is a hollow ink ring, Practice tests a flag pin that turns route blue when open. The puck is a white-rimmed route-blue disc with a white arrowhead and a 16% blue halo, pointed along the road. Labels are 14px 700 ink with a 5px ground-colored halo.

### Cards / Containers
- **Corner Style:** 22px (next card, progress panel, route), 20px (missed list, scenes).
- **Background:** sheet; raised boxes in sheet-raised.
- **Shadow Strategy:** hairline at rest; see Elevation for layered cases.
- **Internal Padding:** 18px, 20px on the sheet.

### Answer Options
Full-width rows, 16px corners, 14px padding, sheet fill and a 1.5px control-line ring, with a 28px rounded-square letter key. Hover: 2px route-blue ring on sheet-raised. After answering: the correct option takes a 2px green ring, correct-soft fill, a green key and a green tag; the wrong pick takes a 2px coral ring and coral key outline and tag, with no fill; the rest fall back to a hairline ring, transparent fill and muted text.

### Progress
A sheet panel with the count in muted 700 (the figure in ink 800) above a bar of equal segments, 6px tall, 4px apart: done segments route blue, the current one a broken route-blue line, the rest hairline.

### Result Line
Leads every answered screen: a 32px circular mark (check on green, cross on coral) and the result text in the result style. A correct result is green text; an incorrect one keeps ink text because it states the correct answer, and only the mark is coral.

### Inputs / Fields
Labels above, 700. Fields are sheet-filled, 54px, 14px corners, 1.5px control-line inner stroke, route-blue caret. Focus is the amber ring at 2px offset. Checkboxes are 22px with route-blue accent.

### Lesson Drawings
Schematic top-down scenes on scene-ground with 20px corners and a hairline. Neutral cars in car-light and car-dark, the Learner's car outlined in route blue (dashed when it is a ghost position), his path a route-blue line on a route-casing under-stroke. Tappable objects wear a thin resting ring (ink at 45%, a 7% blue fill) and an amber outline on hover or focus. After answering, rings and badges settle in over 420ms in the result colors.

## Do's and Don'ts

### Do:
- **Do** put the one thing to do in a single maneuver banner or a single primary button, and step everything else down.
- **Do** carry state by form as well as color: solid for learned, broken for ahead and current, filled key and check for correct, ring and cross for incorrect.
- **Do** mark the Learner's own place, car and path in route blue, and nothing else in it.
- **Do** edge containers with 1px inset hairlines and controls with 1.5px inset strokes on slate sheets.
- **Do** keep every count in tabular numerals and every target at least 44px.
- **Do** gate every animation on reduced-motion preference and ease with cubic-bezier(.16, 1, .3, 1).
- **Do** keep real-world colors in drawings: signs, signals, lane lines and painted cars.

### Don't:
- **Don't** use green or coral in the interface for anything but a correct or incorrect answer.
- **Don't** add a light theme or follow the device's light setting.
- **Don't** add a second typeface.
- **Don't** stack equal-weight blocks like a form page, or dress questions as a gamified quiz card.
- **Don't** use outer borders or hard, unblurred shadows; depth is tone and soft deep-offset shadow.
- **Don't** put a second banner-blue slab on a screen that already has one.
