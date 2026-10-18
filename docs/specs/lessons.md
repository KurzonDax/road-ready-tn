# Lessons

This is the format and the kit. The rules for what a question says and draws, and the steps a lesson goes through, are in `docs/agents/lessons.md`; read that first.

A lesson teaches one Section's facts before any question is asked on them. The Learner acts on every screen before the rule is stated: he taps the car that goes, or commits to a choice, then sees what happens, then the rule in one sentence. The principle of the topic is stated only after two or three cases, and he is asked to name it first. The questions on the Section's facts come after, in the Set.

Lessons are data: one file per Section at `data/lessons/section-<N>.json`, rendered by one player in `src/app.html` from a small kit of top-down drawing parts. Writing a lesson is content work; the drawings stay consistent because the kit draws them.

## A lesson file

```json
{
  "section": 3,
  "title": "Right of way and intersections",
  "steps": [ ...steps in order... ]
}
```

Every one of the Section's 10 facts appears in at least one step with that `fact`. A step with no `fact` is a principle step.

## A step

```json
{
  "id": "s3-01",
  "fact": "b-110",
  "kind": "tap",
  "scene": { "parts": [ ...kit parts... ] },
  "prompt": "Who goes first? Tap the car.",
  "targets": [ {"id": "road-car", "label": "the car on the road"}, {"id": "you", "label": "your car"} ],
  "answer": "road-car",
  "then": {
    "highlight": "road-car",
    "parts": [ ...optional: a full replacement scene showing what happens... ],
    "say": "The car on the road goes first. You are entering the road, so you yield to it."
  },
  "rule": "When you enter a main road from a driveway or a parking lot, you yield to every vehicle on the main road."
}
```

- `kind` is one of `tap`, `choose`, `principle`.
  - `tap`: the Learner taps one part of the drawing. `targets` lists two or more part ids with a spoken label each (the screen reader reads the label; the History stores it). `answer` is the right target's id.
  - `choose`: two to four text `options`, `answer` is one of them. Used for facts with no useful drawing, and for yes/no questions such as "May you turn now?". A `scene` is optional.
  - `principle`: a `choose` after two or more cases, with no `fact`. `prompt` asks what the cases have in common; `options` are two to four candidate sentences; `answer` is the principle. `say` restates it.
- `prompt` is one sentence ending in a question or an instruction.
- `then.say` is one or two sentences: what happens, then why, in plain words. Shown after any action, right or wrong. When the action was wrong the screen also says "You picked: {label}." first. No other wording differs between right and wrong.
- `then.highlight` is a part id drawn in the accent color after the action (the car that goes). `then.parts`, when present, replaces the scene after the action (the car moved through, an arrow drawn). Both optional.
- `rule` is the fact's rule in one complete sentence, in the app's wording standard. Required when `fact` is set. The manual's sentence and page stay in `data/questions.json` to check the step against; the Learner never sees them.

## The kit

The scene is an SVG with `viewBox="0 0 320 320"`, top-down, north up. Roads are two-lane unless said. A standard intersection has the horizontal road from y=130 to y=190 and the vertical road from x=130 to x=190; cars are about 20 by 36. Each part names its type in `t` (`{"t": "car", ...}`). Parts are drawn in the order listed. Colors are neutral except where color is the fact (lane lines, lights, signs).

| part | fields | draws |
|---|---|---|
| `road` | `x, y, w, h`, `center` one of `yellow`, `yellow-broken`, `yellow-double`, `white-broken`, `none` (default `yellow`), or `yellow-pass-n`, `yellow-pass-s`, `yellow-pass-e`, `yellow-pass-w` (a solid and a broken yellow line, the broken one on the side of a driver heading that way), `lanes` (`2` splits each direction into two lanes with a broken white line, a four-lane road) | a road surface with edge lines and the center line along its long side. A driveway or parking-lot exit is a short `road` with `center: "none"`. |
| `circle-road` | `cx, cy, r, w` | a roundabout: a ring road of width `w`. |
| `car` | `id, x, y, heading` (`n`, `e`, `s`, `w`), `you` (bool), `tone` (`a` or `b`, default `a`) | a car centered at x,y with a windshield wedge toward its heading. `you: true` draws it in the accent outline with a "You" label. `id` makes it a tap target or a highlight. |
| `sign` | `kind` (`stop`, `yield`, `allway`), `x, y` | the sign as the manual draws it, small, at a corner. `allway` is a stop sign with an ALL WAY plate. |
| `roadsign` | `kind` (`octagon`, `triangle` pointing down, `diamond`, `circle`, `rectangle`), `color` (`red`, `yellow`, `orange`, `green`, `blue`, `yellow-green`, `white`, `brown`), `x, y`, `id`, `wide` (bool, a rectangle wider than tall) | a sign face about 36 across, drawn by shape and color alone, with no words or symbols on it, so the drawing never says what the sign means. The colors are the ones `data/questions.json` uses. A red triangle has the white middle of a yield sign. Beside a road or on its own. `id` makes it a tap target or a highlight. |
| `light` | `x, y, state` (`red`, `yellow`, `green`, `off`, `flashing-red`, `flashing-yellow`, and with `-left` the lit lamp is a left arrow: `green-left`, `yellow-left`, `red-left`, `flashing-yellow-left`), `span` (default 64, `0` draws no span), `spanX` (the span's center when the head is not over the middle of the road, default the head's `x`) | a traffic signal as the driver meets it: a vertical head, red on top, on a span across the road, over the far side of the intersection. For a car heading north on the standard intersection, `x` 160, `y` 121. A second head on the same span (one lane's arrow beside another lane's light) is a second `light` with `span: 0`. |
| `crosswalk` | `x, y, w, h` | white stripes across the road. |
| `ped` | `id, x, y`, `cane` (bool) | a pedestrian as a dot with shoulders; `cane: true` adds a white cane with a red tip. |
| `path` | `from: [x, y]`, `to: [x, y]`, `via: [x, y]` (optional) | a dashed arrow for where a vehicle intends to go. |
| `label` | `x, y, text`, `anchor` (`start`, `middle`, `end`) | a small text label on the drawing. |

Only cars, pedestrians and road signs can be targets or highlights. Everything a step says in words is also in `prompt`, `say` and `rule`; the drawing never carries a fact on its own.

## How a lesson fits the engine

- A Section's lesson is offered on the home screen before the first Set that would introduce that Section's facts, as the main button. The Set follows it.
- A finished lesson is a `set` record of type `lesson` with the Section number; every step with a fact is one answer with role `lesson` and format `tap` or `choice`. Lesson answers never change a standing.
- In a Set, a new fact whose Section's lesson is finished gets no first look and no rule screen: its first counted question is asked like a due question. A new fact from a Section with no lesson keeps the first look and rule screen.
- After a wrong counted answer on a fact that has a lesson step, the feedback offers "See how this works", which shows that step without recording anything and returns to the Set.
- Every lesson stays open from the home screen under "Lessons", to replay in full.
- A lesson stopped partway is not saved; it starts from its first step next time. Lessons are ten to fifteen steps.

## Validation (`tests/validate_data.py`)

For every `data/lessons/section-N.json`: `section` matches the file name and is a Section in `data/sections.json`; every step `fact` is one of that Section's questions; every one of the Section's questions appears in at least one step; step ids are unique; `kind` is valid; a `tap` step has two or more targets whose ids are `car`, `ped` or `roadsign` parts in its scene, and `answer` is one of them; a `choose` or `principle` step has two to four distinct options and `answer` is one; `prompt`, `then.say` and (with a fact) `rule` are non-empty; `then.highlight`, when present, is a part id in the scene (or in `then.parts`).

## Wording lint and the review sheet

`tests/validate_data.py` (`check_lesson_wording`) refuses lesson text that breaks the owner's wording rules: "yield" for waiting (only a yield sign), "right" for correct, "round" or "your" for a light, "step", "case", unnamed references to earlier screens ("both cases", "these ones"), semicolons, exclamation marks, verdict or praise words, an explanation longer than three sentences, and a tap step that draws an intersection without saying what controls it. `tools/lesson_sheet.py <section> <out.html>` writes a lesson as one page, every screen top to bottom with its drawings before and after the correct action, so a lesson is reviewed as a document.
