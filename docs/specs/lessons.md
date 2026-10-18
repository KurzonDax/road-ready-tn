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
- `then.say` is one or two sentences: what happens, then why, in plain words. Shown after the correct action, and after a wrong one when the step has no `then.wrong`.
- `then.wrong` is an object with one explanation per wrong pick, keyed by the target id (a tap step) or the option text (a choose or principle step): why that pick is wrong, then what is correct, in at most three sentences. Shown instead of `then.say` after that pick, under "Incorrect. You picked {label}." When present it covers every wrong pick of the step. Section 6 has one for every wrong pick.
- `then.highlight` is a part id drawn in the accent color after the action (the car that goes). `then.parts`, when present, replaces the scene after the action (the car moved through, an arrow drawn). Both optional.
- `rule` is the fact's rule in one complete sentence, in the app's wording standard. Required when `fact` is set. The manual's sentence and page stay in `data/questions.json` to check the step against; the Learner never sees them.

## The kit

The scene is an SVG with `viewBox="0 0 320 320"`, top-down, north up (the `bicyclist` is the one part drawn from behind instead). Roads are two-lane unless said. A standard intersection has the horizontal road from y=130 to y=190 and the vertical road from x=130 to x=190; cars are about 20 by 36. Each part names its type in `t` (`{"t": "car", ...}`). Parts are drawn in the order listed. Colors are neutral except where color is the fact (lane lines, lights, signs).

| part | fields | draws |
|---|---|---|
| `road` | `x, y, w, h`, `center` one of `yellow`, `yellow-broken`, `yellow-double`, `white-broken`, `none` (default `yellow`), or `yellow-pass-n`, `yellow-pass-s`, `yellow-pass-e`, `yellow-pass-w` (a solid and a broken yellow line, the broken one on the side of a driver heading that way), `lanes` (`2` splits each direction into two lanes with a broken white line, a four-lane road) | a road surface with edge lines and the center line along its long side. A driveway or parking-lot exit is a short `road` with `center: "none"`. |
| `circle-road` | `cx, cy, r, w` | a roundabout: a ring road of width `w`, one lane, no markings. Its entry roads are `road` parts that end at the ring's outer edge (`cy + r + w / 2`), and a `sign` of kind `yield` stands on the right of each entry the prompt names. Cars in the ring go counter-clockwise, so a car at its west side heads `s` and a car at its east side heads `n`. |
| `car` | `id, x, y, heading` (`n`, `e`, `s`, `w`), `you` (bool), `tone` (`a` or `b`, default `a`), `outline` (bool), `emergency` (bool) | a car centered at x,y with a windshield wedge toward its heading. `you: true` draws it in the accent outline with a "You" label. `outline: true` draws a stopping position instead: the dashed outline of a car where the Learner's car would stand, a tap target for "Where do you stop? Tap the place.", with a `label` beside it that says which place it is ("behind the stop line"). `emergency: true` puts a red and blue flashing light bar on the roof: an emergency vehicle, whose siren the prompt names. `id` makes it a tap target or a highlight. |
| `sign` | `kind` (`stop`, `yield`, `allway`), `x, y` | the sign as the manual draws it, small, at a corner. `allway` is a stop sign with an ALL WAY plate. |
| `roadsign` | `kind` (`octagon`, `triangle` pointing down, `diamond`, `circle`, `rectangle`), `color` (`red`, `yellow`, `orange`, `green`, `blue`, `yellow-green`, `white`, `brown`), `x, y`, `id`, `wide` (bool, a rectangle wider than tall) | a sign face about 36 across, drawn by shape and color alone, with no words or symbols on it, so the drawing never says what the sign means. The colors are the ones `data/questions.json` uses. A red triangle has the white middle of a yield sign. Beside a road or on its own. `id` makes it a tap target or a highlight. |
| `light` | `x, y, state` (`red`, `yellow`, `green`, `off`, `flashing-red`, `flashing-yellow`, and with `-left` the lit lamp is a left arrow: `green-left`, `yellow-left`, `red-left`, `flashing-yellow-left`), `span` (default 64, `0` draws no span), `spanX` (the span's center when the head is not over the middle of the road, default the head's `x`) | a traffic signal as the driver meets it: a vertical head, red on top, on a span across the road, over the far side of the intersection. For a car heading north on the standard intersection, `x` 160, `y` 121. A second head on the same span (one lane's arrow beside another lane's light) is a second `light` with `span: 0`. |
| `crosswalk` | `x, y, w, h` | white stripes across the road. |
| `stopline` | `x, y, w, h` (default `h` 5) | a painted stop line: a white bar across the lane before a stop sign or a railroad crossing. |
| `bus` | `x, y, heading`, `lights` (`off`, `yellow`, `red`), `arm` (bool) | a school bus: a yellow body about 24 by 60 with a black stripe and a windshield at the front, four warning lamps at its corners that flash yellow or red when `lights` says so, and with `arm: true` the red stop arm swung out on the driver's side. Not a target. The prompt says what the lights and the arm are doing. |
| `rails` | `x, y, w, h` | railroad tracks across a road: two rails on ties along the long side of the box. |
| `crossbuck` | `x, y`, `lights` (`off`, `flashing`), `gate` (`none`, `up`, `down`), `gateLen` (default 56), `gateDir` (`e` default, `w`, `n`, `s`) | a railroad crossing signal at the roadside: a white crossbuck on a post, two lamps under it that flash red when `lights` is `flashing`, and a gate: `down` is a red and white arm reaching `gateLen` from the post toward `gateDir`, across the lane, `up` a short stub standing on the post. The prompt says whether the lights flash and whether the gate is down. |
| `median` | `x, y, w, h` | a median strip between the two roadways of a divided highway: a raised strip with a curb on each side, which cars cannot drive on. The two roadways are two `road` parts with `center: "white-broken"`. |
| `lane` | `id, x, y, w, h` | a lane box (Section 6): a dashed box centered at x,y filling a stretch of one lane, with nothing written on it (the prompt and the target labels name the lanes, and text inside the box was too small to read), a tap target for "Which lane do you turn into? Tap the lane." and "Which lane do you turn from? Tap the lane." The whole box is the hit area and the marks are drawn on the box, so boxes sit side by side in adjacent lanes. A lane question is a close-up: lanes 60 to 70 wide, the Learner heading north, the two lanes he could use each holding a box at least 54 by 50, and after the tap `then.parts` puts his car at the correct box's place and keeps the other box. `id` makes it a tap target or a highlight. |
| `bicyclist` | `x, y` (default 160, 160), `arm` (`left-out`, `left-up`, `left-down`, `right-out`, `right-down`, `none`) | a bicyclist seen from behind, as the driver behind sees him: the one part that is not top-down, because an arm bent up or down cannot be seen from above. One arm is held in the signal `arm` names (straight out, or bent at the elbow with the hand up or down) and the other holds the handlebar. Fills the drawing on its own, over a strip of road; a scene with a bicyclist holds nothing else. Not a target. The prompt says which arm and how it is held. |
| `post` | `x, y` | a fixed point at the roadside, seen from above: a short post with a small plate on it, the thing the car ahead passes when the Learner counts his following distance. It is not a target. A `label` beside it says what it is. |
| `ped` | `id, x, y`, `cane` (bool) | a pedestrian as a dot with shoulders; `cane: true` adds a white cane with a red tip. |
| `path` | `from: [x, y]`, `to: [x, y]`, `via: [x, y]` (optional) | a dashed arrow for where a vehicle intends to go. |
| `label` | `x, y, text`, `anchor` (`start`, `middle`, `end`) | a small text label on the drawing. |

Only cars (a stopping position is a car with `outline: true`), pedestrians, road signs and lane boxes can be targets or highlights. Everything a step says in words is also in `prompt`, `say` and `rule`; the drawing never carries a fact on its own.

## How a lesson fits the engine

- A Section's lesson is offered on the home screen before the first Set that would introduce that Section's facts, as the main button. The Set follows it.
- A finished lesson is a `set` record of type `lesson` with the Section number; every step with a fact is one answer with role `lesson` and format `tap` or `choice`. Lesson answers never change a standing.
- In a Set, a new fact whose Section's lesson is finished gets no first look and no rule screen: its first counted question is asked like a due question. A new fact from a Section with no lesson keeps the first look and rule screen.
- After a wrong counted answer on a fact that has a lesson step, the feedback offers "See how this works", which shows that step without recording anything and returns to the Set.
- Every lesson stays open from the home screen under "Lessons", to replay in full.
- A lesson stopped partway is not saved; it starts from its first step next time. Lessons are ten to fifteen steps.

## Validation (`tests/validate_data.py`)

For every `data/lessons/section-N.json`: `section` matches the file name and is a Section in `data/sections.json`; every step `fact` is one of that Section's questions; every one of the Section's questions appears in at least one step; step ids are unique; `kind` is valid; a `tap` step has two or more targets whose ids are `car`, `ped`, `roadsign` or `lane` parts in its scene, and `answer` is one of them; a `choose` or `principle` step has two to four distinct options and `answer` is one; `prompt`, `then.say` and (with a fact) `rule` are non-empty; `then.wrong`, when present, has one non-empty explanation for each wrong target or option and no other key; `then.highlight`, when present, is a part id in the scene (or in `then.parts`).

## Wording lint and the review sheet

`tests/validate_data.py` (`check_lesson_wording`) refuses lesson text that breaks the owner's wording rules: "yield" for waiting (only a yield sign), "right" for correct, "round" or "your" for a light, "step", "case", unnamed references to earlier screens ("both cases", "these ones"), semicolons, exclamation marks, verdict or praise words, an explanation longer than three sentences, and a tap step that draws an intersection without saying what controls it. `tools/lesson_sheet.py <section> <out.html>` writes a lesson as one page, every screen top to bottom with its drawings before and after the correct action, so a lesson is reviewed as a document.
