#!/usr/bin/env python3
"""Check each Section's lesson against what the owner set for that Section, on the data alone.

The rules every lesson follows (10 to 15 steps, a then.wrong for every wrong pick, the form of the options,
the wording lint, the kit's part types) are in tests/validate_data.py. This holds what is particular to one
Section: its question forms, what each drawing shows, which facts its questions teach, and the manual's
numbers in their answers. It reads data/lessons/section-N.json, the Section's facts in data/sections.json and
data/questions.json, and needs no browser, no server and no build. What the page draws and does with a lesson
is checked by tests/test_app.py check_lessons.

Usage:
    python3 tests/test_lessons.py
"""
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
SECTIONS = {s["section"]: s["questions"] for s in json.loads((ROOT / "data" / "sections.json").read_text())["sections"]}
BANK = {q["id"]: q for q in json.loads((ROOT / "data" / "questions.json").read_text())["questions"]}
failures = []


def check(cond, msg, got=None):
    """Print and count one check. `got`, when given, is shown only if the check fails."""
    if not cond and got is not None:
        msg += f" (got {got})"
    print(("  ok    " if cond else "  FAIL  ") + msg)
    if not cond:
        failures.append(msg)


def steps_of(section):
    """The Section's lesson steps, each with the fields the checks read: `parts` is the scene's parts ([] when it has
    none), `after` is then.parts, and a missing fact, wrong, options, targets, after or highlight is None."""
    lesson = json.loads((ROOT / "data" / "lessons" / f"section-{section}.json").read_text())
    return [{"id": s.get("id"), "kind": s.get("kind"), "fact": s.get("fact") or None, "answer": s.get("answer"),
             "prompt": s.get("prompt", ""), "say": s["then"].get("say", ""), "wrong": s["then"].get("wrong") or None,
             "options": s.get("options") or None, "targets": s.get("targets") or None,
             "parts": (s.get("scene") or {}).get("parts", []), "after": s["then"].get("parts") or None,
             "highlight": s["then"].get("highlight") or None} for s in lesson["steps"]]


def parse_int(text):
    """The whole number a text starts with, as JavaScript's parseInt reads it ("15 feet" -> 15), or None."""
    m = re.match(r"\s*([+-]?\d+)", text)
    return int(m.group(1)) if m else None


def sentence_options(steps):
    """Every principle question's options are complete sentences or a plain Yes or No. validate_data.py holds the
    same rule for choose questions and leaves principle questions out, because Section 3's closing question asks
    questions; in Sections 4 and 6 the principle options are sentences."""
    return all(all(o == "Yes" or o == "No" or o.endswith(".") for o in s["options"]) for s in steps if s["kind"] == "principle")


def section_1(steps, facts):
    """Signs: shapes and colors."""
    taps = [s for s in steps if s["kind"] == "tap"]
    check(taps and all(s["targets"] and all(any(p["t"] == "roadsign" and p.get("id") == t["id"] for p in s["parts"]) for t in s["targets"])
                       for s in taps), "every tap target in the lesson is a road sign in its scene")
    check(all(s["prompt"].startswith("Which sign ") and s["prompt"].endswith("? Tap the sign.") for s in taps),
          "every tap question is the one form, Which sign ...? Tap the sign., with no list of the signs before it")
    check(steps[0]["kind"] == "tap", "the first question is a tap on a sign")


def section_2(steps, facts):
    """Signals, arrows and road lines."""
    taps = [s for s in steps if s["kind"] == "tap"]
    check(taps and all(s["prompt"].endswith("Who goes first? Tap the car.") and all(any(p["t"] == "car" and p.get("id") == t["id"] for p in s["parts"]) for t in s["targets"])
                       for s in taps), "every tap question asks who goes first, in the one form, and its targets are cars in the scene")
    lights = [s for s in steps if any(p["t"] == "light" for p in s["parts"])]
    mine = lambda s: next(p for p in s["parts"] if p["t"] == "light")  # the head over the Learner's lane is listed first
    check(lights and all(mine(s)["state"].replace("flashing-", "").replace("-left", "") in s["prompt"].lower()
                         and bool(re.search(r"(?<!not )flashing", s["prompt"].lower())) == mine(s)["state"].startswith("flashing") for s in lights),
          "every prompt with a light says its color, and says flashing (not \"not flashing\") exactly when the Learner's light flashes")
    lines = [s for s in steps if s["parts"] and len([p for p in s["parts"] if p["t"] == "road"]) == 1]
    check(lines and all(("white" in s["prompt"].lower()) == (s["parts"][0].get("center", "yellow").startswith("white"))
                        and ("yellow" in s["prompt"].lower()) == (s["parts"][0].get("center", "yellow").startswith("yellow")) for s in lines),
          "every prompt about one stretch of road names the color of its center line")
    arrows = [s for s in steps if any(p["t"] == "light" and p["state"].endswith("-left") for p in s["parts"])]
    check(len(arrows) >= 4 and all("arrow" in s["prompt"] for s in arrows), "the arrow questions say arrow in the prompt")
    first = steps[0]
    check(first["kind"] == "choose" and first["parts"], "the first question is a choice about a drawn scene")


def section_4(steps, facts):
    """Speed and following distance."""
    check(all(s["kind"] in ("choose", "principle") for s in steps) and all((s["kind"] == "principle") == (s["fact"] is None) for s in steps),
          "every question is a choice, and only the principle questions have no fact")
    check(sentence_options(steps), "every principle option is a complete sentence or a plain Yes or No")
    numbers = [s for s in steps if s["fact"] in ("b-031", "b-030")]
    check(len(numbers) == 2 and all(any(p["t"] == "road" for p in s["parts"]) and "No speed limit sign is posted" in s["prompt"] for s in numbers)
          and all(re.search(r"\b(70|55) mph\b", s["answer"]) for s in numbers),
          "the two speed limit questions draw the road, say that no sign is posted, and answer with the manual's number")
    posts = [s for s in steps if any(p["t"] == "post" for p in s["parts"])]
    check(len(posts) >= 2 and all("sign post" in s["prompt"] and any(p["t"] == "car" and not p.get("you") for p in s["parts"]) for s in posts),
          "the following-distance questions draw a roadside post the prompt names, with a car ahead", len(posts))
    check(not any(re.search(r"\b(feet|ft|car lengths?)\b", s["prompt"] + " " + s["answer"]) for s in steps if s["fact"]),
          "no answer measures a distance in feet or car lengths")
    # The counting method is used before it is asked about: the first b-053 question states the count and asks what follows,
    # and the question that asks him to choose the method comes after the one where he acted on a short count (b-054).
    method = [k for k, s in enumerate(steps) if s["fact"] == "b-053"]
    acted = next(k for k, s in enumerate(steps) if s["fact"] == "b-054")
    check(len(method) == 2 and "one-thousand and two" in steps[method[0]]["prompt"] and "two seconds behind" in steps[method[0]]["answer"]
          and method[0] < acted < method[1] and steps[method[1]]["answer"].startswith("You count the seconds"),
          "the count is stated and used before the question that asks for the method", method)
    first = steps[0]
    check(first["kind"] == "choose" and first["parts"] and first["fact"] == "b-031", "the first question is a choice about a drawn interstate")


def section_5(steps, facts):
    """Stops you must make."""
    check(all(s["fact"] for s in steps), "every question has a fact")
    taps = [s for s in steps if s["kind"] == "tap"]
    check(len(taps) >= 3 and all(s["prompt"].endswith("Where do you stop? Tap the place.") for s in taps),
          "every tap question asks where you stop, in the same words", len(taps))

    def places_named(s):
        outlines = {p["id"] for p in s["parts"] if p["t"] == "car" and p.get("outline")}
        labels = " ".join(p["text"] for p in s["parts"] if p["t"] == "label")
        return {t["id"] for t in s["targets"]} == outlines and all(t["label"].split(" of ")[0] in labels for t in s["targets"])
    check(all(places_named(s) for s in taps) and all(sum(1 for t in s["targets"] if t["id"] == s["answer"]) == 1 for s in taps),
          "the targets of a tap question are the drawn stopping places, each named by a label on the drawing, and exactly one is the answer")
    buses = [s for s in steps if any(p["t"] == "bus" for p in s["parts"])]

    def bus_as_said(s):
        bus = next(p for p in s["parts"] if p["t"] == "bus")
        if "yellow lights" in s["prompt"]: return bus.get("lights") == "yellow" and not bus.get("arm")
        if "red lights" in s["prompt"]: return bus.get("lights") == "red" and bus.get("arm") is True
        return "stopped" in s["prompt"]  # a stopped bus whose lights the decision does not turn on
    check(len(buses) >= 5 and all(bus_as_said(s) for s in buses), "every school bus is drawn with the lights and the stop arm the prompt names", len(buses))
    crossings = [s for s in steps if any(p["t"] == "crossbuck" for p in s["parts"])]

    def crossing_as_said(s):
        cb = next(p for p in s["parts"] if p["t"] == "crossbuck")
        # Where the prompt names the gate or the lights, the drawing agrees; a train coming means the gate is down and the lights flash.
        gate_said = "gate is" in s["prompt"]
        down = "gate is down" in s["prompt"] or "gate is still down" in s["prompt"] or ("A train is coming" in s["prompt"] and "gate is" not in s["prompt"])
        flashing = ("flashing" in s["prompt"] and "stopped flashing" not in s["prompt"]) or "A train is coming" in s["prompt"]
        return (not gate_said or (cb.get("gate") == "down") == down) and (cb.get("lights") == "flashing") == flashing and any(p["t"] == "rails" for p in s["parts"])
    check(len(crossings) >= 3 and all(crossing_as_said(s) for s in crossings), "every railroad crossing draws the tracks, and its gate and lights as the prompt says", len(crossings))
    check(any(any(p["t"] == "median" for p in s["parts"]) and "median" in s["prompt"] for s in steps if s["fact"] == "b-089"),
          "the divided-highway question draws the median the prompt names")
    sirens = [s for s in steps if "siren" in s["prompt"]]
    check(len(sirens) == 3 and all(any(p["t"] == "car" and p.get("emergency") for p in s["parts"]) for s in sirens),
          "every emergency-vehicle question draws a vehicle with its lights, and name the siren")
    # The distance from the tracks is asked as the test asks it, then used: a tap where the prompt says the stop line is 30 feet from the tracks.
    distance = [s for s in steps if s["fact"] == "b-077"]
    check(len(distance) == 2 and distance[0]["kind"] == "choose" and distance[0]["answer"] == "Between 15 and 50 feet from the tracks."
          and distance[1]["kind"] == "tap" and "30 feet from the tracks" in distance[1]["prompt"] and distance[1]["targets"][[t["id"] for t in distance[1]["targets"]].index(distance[1]["answer"])]["label"] == "behind the stop line"
          and all(any(p["t"] == "stopline" for p in s["parts"]) == ("stop line" in s["prompt"]) for s in crossings if s["fact"] == "b-077"),
          "the distance from the tracks is a choice of the manual's ranges, then a tap behind the stop line the prompt places 30 feet from the tracks")
    first = steps[0]
    check(first["kind"] == "tap" and first["fact"] == "b-064", "the first question is a tap on the stop line question")


def section_6(steps, facts):
    """Turning and signaling."""
    check(all((s["kind"] == "principle") == (s["fact"] is None) for s in steps), "only a principle question has no fact")
    check(sentence_options(steps), "every principle option is a complete sentence or a plain Yes or No")
    check(all(not s["parts"] and s["kind"] == "choose" for s in steps if s["fact"] in ("a-004", "a-003")), "the seat and hand questions are choices with no drawing")
    riders = [s for s in steps if s["fact"] == "d-097"]
    POSES = {"straight out": "left-out", "bent up": "left-up", "bent down": "left-down"}

    def rider_as_said(s):
        bike = [p for p in s["parts"] if p["t"] == "bicyclist"]
        pose = next((v for k, v in POSES.items() if k in s["prompt"]), None)
        return s["kind"] == "choose" and len(s["parts"]) == 1 and len(bike) == 1 and bike[0]["arm"] == pose and "behind a bicyclist" in s["prompt"]
    check(len(riders) == 3 and all(rider_as_said(s) for s in riders) and {s["parts"][0]["arm"] for s in riders} == set(POSES.values())
          and [s["answer"].split()[-1] for s in sorted(riders, key=lambda s: s["parts"][0]["arm"])] == ["down.", "left.", "right."],
          "the three hand signals are each a choice with the bicyclist drawn from behind, the arm as the prompt says, and the answer the manual gives")
    taps = [s for s in steps if s["kind"] == "tap"]
    FORMS = ("Who goes first? Tap the car.", "Which lane do you turn into? Tap the lane.", "Which lane do you turn from? Tap the lane.")
    check(len(taps) >= 5 and all(s["prompt"].endswith(FORMS) for s in taps), "every tap question ends in one of the three forms", len(taps))
    check(all(all(any(p["t"] in ("car", "lane") and p.get("id") == t["id"] for p in s["parts"]) for t in s["targets"]) and sum(1 for t in s["targets"] if t["id"] == s["answer"]) == 1 for s in taps),
          "every tap target is a car or a lane box in its scene, and exactly one is the answer")
    lanes = [s for s in taps if "Tap the lane." in s["prompt"]]

    def lanes_named(s):
        boxes = {p["id"] for p in s["parts"] if p["t"] == "lane"}
        return {t["id"] for t in s["targets"]} == boxes and not any("label" in p for p in s["parts"] if p["t"] == "lane")

    def you_in_lane(s):
        where = next(p for p in s["parts"] if p.get("id") == s["answer"])
        return s["after"] and any(p["t"] == "car" and p.get("you") and not p.get("outline") and (p["x"], p["y"]) == (where["x"], where["y"]) for p in s["after"])

    def side_by_side(s):
        a, b = [p for p in s["parts"] if p["t"] == "lane"]
        gap = max(abs(a["x"] - b["x"]) - (a["w"] + b["w"]) / 2, abs(a["y"] - b["y"]) - (a["h"] + b["h"]) / 2)
        return 0 < gap <= 10 and all(p["w"] >= 50 and p["h"] >= 50 for p in (a, b))
    check(all(side_by_side(s) for s in lanes), "the two lane boxes of a lane question sit side by side, each at least 50 by 50")
    check({s["fact"] for s in lanes} == {"b-169", "b-159", "b-163"} and all(lanes_named(s) and you_in_lane(s) for s in lanes),
          "the three lane questions tap lane boxes with nothing written on them, and afterwards your car stands in the correct lane")
    check(all(("one-way" in s["prompt"]) == (s["fact"] == "b-163") and ("two-way" in s["prompt"]) == (s["fact"] != "b-163") for s in lanes)
          and all(("turn right" in s["prompt"]) == (s["fact"] == "b-169") and ("turn left" in s["prompt"]) == (s["fact"] != "b-169") for s in lanes),
          "every lane prompt says whether the streets are one-way or two-way and which way the turn goes")
    rings = [s for s in steps if any(p["t"] == "circle-road" for p in s["parts"])]
    check(len(rings) == 2 and all(s["kind"] == "tap" and s["fact"] == "b-174" and "roundabout" in s["prompt"] and "yield sign" in s["prompt"]
                                  and any(p["t"] == "sign" and p["kind"] == "yield" for p in s["parts"]) for s in rings)
          and {s["answer"] for s in rings} == {"you", next(t["id"] for t in rings[0]["targets"] if t["id"] != "you")},
          "the two roundabout questions draw the ring road and the yield sign the prompt names, and the car already in the roundabout goes first each time")
    reds = [s for s in steps if s["fact"] == "a-146"]
    check(len(reds) == 2 and all(s["kind"] == "choose" and "red light" in s["prompt"] and any(p["t"] == "light" and p["state"] == "red" for p in s["parts"]) for s in reds)
          and [s["answer"] for s in reds] == ["Yes", "No"], "the right-on-red questions draw a red light the prompt names, with the clear turn allowed and the blocked one not")
    signal = next(s for s in steps if s["fact"] == "b-139")
    check(signal["kind"] == "tap" and "signal" in signal["prompt"] and signal["answer"] != "you", "the signal gives no right-of-way: the oncoming car goes first")
    first = steps[0]
    check(first["kind"] == "choose" and not first["parts"], "the first question is a choice with no drawing")


def section_7(steps, facts):
    """Lanes and passing."""
    check(all(s["fact"] for s in steps), "every question has a fact")
    taps = [s for s in steps if s["kind"] == "tap"]
    check(len(taps) == 2 and all(s["prompt"].startswith("You are the red car. You want to pass the ") and s["prompt"].endswith("Which lane do you use to pass? Tap the lane.") for s in taps)
          and {s["fact"] for s in taps} == {"a-176", "d-106"},
          "the two tap questions say you are the red car and ask which lane you use to pass, in the one form, for the broken white line and the motorcycle")

    def painted(s):
        cars = [p for p in s["parts"] if p["t"] == "car"]
        return all((p.get("color") == "red") == bool(p.get("you")) and p.get("color") in ("red", "blue") for p in cars)
    check(all(painted(s) and s["prompt"].startswith("You are the red car") for s in steps), "every question paints your car red and the other car blue, and the prompt says so")

    def boxes_only(s):
        boxes = {p["id"] for p in s["parts"] if p["t"] == "lane"}
        return {t["id"] for t in s["targets"]} == boxes and not any("label" in p for p in s["parts"] if p["t"] == "lane") and sum(1 for t in s["targets"] if t["id"] == s["answer"]) == 1

    def side_by_side(s):
        a, b = [p for p in s["parts"] if p["t"] == "lane"]
        gap = max(abs(a["x"] - b["x"]) - (a["w"] + b["w"]) / 2, abs(a["y"] - b["y"]) - (a["h"] + b["h"]) / 2)
        return 0 < gap <= 10 and all(p["w"] >= 50 and p["h"] >= 50 for p in (a, b))

    def you_in_lane(s):
        where = next(p for p in s["parts"] if p.get("id") == s["answer"])
        return s["after"] and any(p["t"] == "car" and p.get("you") and (p["x"], p["y"]) == (where["x"], where["y"]) for p in s["after"]) \
            and any(p["t"] == "lane" and p["id"] != s["answer"] for p in s["after"])
    check(all(boxes_only(s) and side_by_side(s) and you_in_lane(s) for s in taps),
          "each tap question's targets are two lane boxes side by side with nothing written on them, one the answer, and afterwards your car stands in it")
    moto = next(s for s in taps if s["fact"] == "d-106")
    check("motorcycle" in moto["prompt"] and any(p["t"] == "bike" and p.get("motor") for p in moto["parts"]) and any(p["t"] == "bike" and p.get("motor") for p in moto["after"]),
          "the motorcycle question draws a motorcycle the prompt names, before and after the tap")

    # Every prompt about a line names its color and whether it is solid or broken, as the road is drawn.
    def line_said(s):
        c = next((p.get("center", "yellow") for p in s["parts"] if p["t"] == "road"), None)
        pr = s["prompt"].lower()
        if s["fact"] == "a-176": return "broken white" in s["say"].lower() and "solid yellow" in " ".join(s["wrong"].values()).lower() and c == "yellow-double"
        if s["fact"] == "a-166": return "broken white" in pr and "solid yellow" in pr and c == "yellow-double"
        if s["fact"] == "a-170": return "two solid yellow" in pr and c == "yellow-double"
        if s["fact"] == "b-223": return "broken" in pr and "yellow" in pr and c == "yellow-pass-n"
        return True
    check(all(line_said(s) for s in steps), "the line questions name each line's color and whether it is solid or broken, in the prompt or the explanation, and draw it so")
    wrong_way = next(s for s in steps if s["fact"] == "a-166")
    you = next(p for p in wrong_way["parts"] if p["t"] == "car" and p.get("you"))
    road = next(p for p in wrong_way["parts"] if p["t"] == "road")
    check(wrong_way["answer"] == "You are going the wrong way." and you["heading"] == "n" and you["x"] < road["x"] + road["w"] / 2,
          "the wrong-way question draws your car heading north in the lanes for southbound cars, and the answer is the test's phrase")
    hill = next(s for s in steps if s["fact"] == "b-223")
    check(hill["kind"] == "choose" and "hill" in hill["prompt"] and hill["answer"] == "No" and any(p["t"] == "zone" for p in hill["parts"]) and any(p["t"] == "label" for p in hill["parts"]),
          "the hill question draws the hidden road as a shaded, labelled stretch and answers No")
    bike = next(s for s in steps if s["fact"] == "b-228")
    check(bike["kind"] == "choose" and "3 feet" in bike["answer"] and any(p["t"] == "bike" and not p.get("motor") for p in bike["parts"])
          and not any(p["t"] == "measure" for p in bike["parts"]) and any(p["t"] == "measure" and "3 feet" in p["text"] for p in bike["after"]),
          "the bicycle question draws a bicycle, and the 3 feet measure appears only after acting")
    blind = next(s for s in steps if s["fact"] == "b-207")
    check(blind["kind"] == "choose" and "shoulder" in blind["answer"] and any(p["t"] == "zone" for p in blind["parts"]) and "shaded" in blind["prompt"],
          "the blind-spot question shades the spot the prompt names, and the answer is to look over your shoulder")
    back = next(s for s in steps if s["fact"] == "d-018")
    check(back["kind"] == "choose" and "both" in back["answer"] and "headlights" in back["answer"] and "mirror" in back["answer"],
          "the question on returning after a pass answers with both headlights in the mirror")
    rights = [s for s in steps if s["fact"] == "b-215"]
    check(len(rights) == 2 and [s["answer"] for s in rights] == ["Yes", "No"] and "left turn signal" in rights[0]["prompt"] and "shoulder" in rights[1]["prompt"]
          and any(p["t"] == "label" and p["text"] == "Driveway" for p in rights[0]["parts"]) and any(p["t"] == "label" and p["text"] == "Shoulder" for p in rights[1]["parts"]),
          "passing on the right is allowed beside the car turning left into the driveway and not on the shoulder, each drawn with its label")
    trucks = [s for s in steps if s["fact"] == "d-116"]
    check(len(trucks) == 2 and all(s["kind"] == "choose" and any(p["t"] == "truck" for p in s["parts"]) and not any(p["t"] == "zone" for p in s["parts"])
                                   and len([p for p in s["after"] if p["t"] == "zone"]) == 4 for s in trucks)
          and "100 feet" in trucks[0]["prompt"] and trucks[0]["answer"] == "No" and any(p["t"] == "measure" and p["text"] == "200 feet" for p in trucks[0]["after"]),
          "the truck questions draw the truck with its four blind spots shaded only after acting, and the 200 feet measure on the one behind")
    first = steps[0]
    check(first["kind"] == "tap" and first["fact"] == "a-176", "the first question is the broken white line tap")


def section_8(steps, facts):
    """Parking."""
    check(all(s["fact"] for s in steps), "every question has a fact")
    check(all(s["prompt"].startswith("You are the red car") for s in steps if s["parts"])
          and all(all((p.get("color") == "red") == bool(p.get("you")) for p in s["parts"] if p["t"] == "car") for s in steps),
          "every question with a drawing says you are the red car, and only your car is red")
    # The pull-out question: a tap on the blue car coming up behind, with your car at the curb and a path into the lane.
    out = next(s for s in steps if s["fact"] == "b-249")
    check(out["kind"] == "tap" and out["prompt"].endswith("Who goes first? Tap the car.") and "signal" in out["prompt"] and "looked" in out["prompt"]
          and any(p["t"] == "car" and p.get("color") == "blue" and p.get("id") == out["answer"] for p in out["parts"]) and any(p["t"] == "path" for p in out["parts"]),
          "the pull-out question asks who goes first, with your signal on, and the blue car coming up behind is the answer")
    # The four distance questions: one street, the thing the prompt names, three spaces side by side along the curb at measured
    # distances, the measures in the scene, and the middle one the closest space the law allows.
    LIMITS = {"b-250": ("fire hydrant", "hydrant", 15), "b-252": ("crosswalk", "crosswalk", 20), "b-253": ("stop sign", "sign", 30), "b-251": ("railroad crossing", "rails", 50)}
    dist = [s for s in steps if s["fact"] in LIMITS]
    test_numbers = {i: [n for n in (parse_int(o) for o in [BANK[i]["answer"], *BANK[i]["wrong"]]) if n is not None and n > 0] for i in facts}

    def street(s):
        name, part, limit = LIMITS[s["fact"]]
        spaces = [p for p in s["parts"] if p["t"] == "space"]
        measures = [p for p in s["parts"] if p["t"] == "measure"]
        feet = {}
        for t in s["targets"]:
            m = re.search(r"the space (\d+) feet from the " + name, t["label"])
            if m: feet[t["id"]] = int(m.group(1))
        by_x = sorted(spaces, key=lambda p: -p["x"])  # nearest the thing first
        gaps = [by_x[k]["x"] - by_x[k + 1]["x"] - 36 for k in range(len(by_x) - 1)]
        said = f"You are the red car. The three spaces are {feet.get('near')}, {feet.get('middle')} and {feet.get('far')} feet from the {name}. You want to park as close to it as the law allows. Which space do you use? Tap the space."
        return (s["kind"] == "tap" and s["prompt"] == said
                and any(p["t"] == part for p in s["parts"]) and len(spaces) == 3 and {p["id"] for p in spaces} == set(feet) == {t["id"] for t in s["targets"]}
                and all(p["y"] == spaces[0]["y"] and p["w"] >= 30 and p["h"] >= 20 and "label" not in p for p in spaces) and all(10 <= g <= 110 for g in gaps)
                and [p["id"] for p in by_x] == ["near", "middle", "far"] and feet["near"] < limit == feet["middle"] < feet["far"] and s["answer"] == "middle"
                and sorted(m["text"] for m in measures) == sorted(f"{d} feet" for d in feet.values()) and s["highlight"] == "middle"
                and {feet["near"], feet["far"]} <= set(test_numbers[s["fact"]])
                and f"{limit} feet" in s["say"] and all(f"{limit} feet" in w for w in s["wrong"].values()) and f"{feet['middle']} feet" in s["wrong"]["near"] and f"{feet['middle']} feet" in s["wrong"]["far"])
    check(len(dist) == 4 and all(street(s) for s in dist),
          "each distance question draws its thing and three spaces side by side with their measures, the middle space is at the manual's number, the others at the test's wrong numbers, and every explanation gives the limit")
    stop = next(s for s in dist if s["fact"] == "b-253")
    check("stop sign" in stop["prompt"] and len([p for p in stop["parts"] if p["t"] == "road"]) == 2 and any(p["t"] == "sign" and p["kind"] == "stop" for p in stop["parts"]),
          "the stop sign question draws the cross street with the stop sign at its corner, and the prompt names the sign")
    rail = next(s for s in dist if s["fact"] == "b-251")
    check(any(p["t"] == "crossbuck" and p.get("lights") == "off" and p.get("gate") == "none" for p in rail["parts"]), "the railroad question draws the crossbuck beside the tracks, lights off and no gate down")
    # The hill questions: the hill from the side on top, two wheel pictures side by side under it, the curb as the prompt says.
    hills = [s for s in steps if s["fact"] in ("b-260", "b-261", "b-262")]

    def hill(s):
        h = [p for p in s["parts"] if p["t"] == "hill"]
        boxes = sorted((p for p in s["parts"] if p["t"] == "wheels"), key=lambda p: p["x"])
        curb = "there is a curb on your right" in s["prompt"]
        facing = "downhill" if "facing downhill" in s["prompt"] else "uphill" if "facing uphill" in s["prompt"] else None
        gap = boxes[1]["x"] - boxes[0]["x"] - (boxes[0]["w"] + boxes[1]["w"]) / 2 if len(boxes) == 2 else None
        side = "the curb" if curb else "the edge of the road"
        return (s["kind"] == "tap" and s["prompt"].endswith("Which way do you turn your front wheels? Tap the wheels.") and len(h) == 1 and len(boxes) == 2
                and (curb or "there is no curb" in s["prompt"]) and facing and h[0]["facing"] == facing[:-4] and bool(h[0].get("curb")) == curb
                and all(bool(p.get("curb")) == curb and p["w"] >= 140 and p["h"] >= 130 and "label" not in p for p in boxes) and 0 < gap <= 10
                and {p["id"]: p["turn"] for p in boxes} == {"toward": "toward", "away": "away"} and {t["id"] for t in s["targets"]} == {"toward", "away"}
                and all(t["label"] == f"the front wheels turned {t['id']} {'from ' if t['id'] == 'away' else ''}{side}" for t in s["targets"])
                and s["answer"] == s["highlight"] == {("downhill", True): "toward", ("uphill", True): "away", ("downhill", False): "toward", ("uphill", False): "toward"}[(facing, curb)])
    check(len(hills) == 4 and all(hill(s) for s in hills) and {(s["parts"][0]["facing"], bool(s["parts"][0].get("curb"))) for s in hills} == {("down", True), ("up", True), ("down", False), ("up", False)},
          "the four hill questions draw the hill from the side with two wheel pictures side by side, cover both slopes with and without a curb, and answer as the manual does")
    bridge = next(s for s in steps if s["fact"] == "b-256")
    check(bridge["kind"] == "choose" and not bridge["parts"] and "bridge" in bridge["answer"] and "tunnel" in bridge["answer"], "the illegal-places question is a choice answered with the bridge or the tunnel")
    curb = next(s for s in steps if s["fact"] == "b-268")
    check(curb["kind"] == "choose" and "18 inches" in curb["answer"] and any(p["t"] == "car" and p.get("you") for p in curb["parts"]) and not any(p["t"] == "measure" for p in curb["parts"]),
          "the parallel parking question is a choice answered with 18 inches, drawn with your car at the curb and no measure")
    check(steps[0]["fact"] == "b-249", "the first question is the pull-out tap")


def section_9(steps, facts):
    """Interstate driving."""
    check(all(s["fact"] for s in steps), "every question has a fact")
    check(all(s["parts"] and s["prompt"].startswith("You are the red car") for s in steps)
          and all(all((p.get("color") == "red") == bool(p.get("you")) for p in s["parts"] if p["t"] == "car") for s in steps),
          "every question draws a scene and says you are the red car, and only your car is red")
    check(all(len([p for p in s["parts"] if p["t"] == "road"]) == 1 for s in steps if s["kind"] == "tap"), "every tap question draws one roadway, a close-up")
    by_fact = lambda f: [s for s in steps if s["fact"] == f]
    # The lane questions: one form, lane boxes side by side as the targets, your car in the correct box afterwards.
    lanes = [s for s in steps if s["kind"] == "tap" and s["fact"] != "c-004"]

    def lane_q(s):
        boxes = sorted((p for p in s["parts"] if p["t"] == "lane"), key=lambda p: p["x"])
        gaps = [boxes[k + 1]["x"] - boxes[k]["x"] - (boxes[k]["w"] + boxes[k + 1]["w"]) / 2 for k in range(len(boxes) - 1)]
        box = next(p for p in boxes if p["id"] == s["answer"])
        you = next((p for p in (s["after"] or []) if p["t"] == "car" and p.get("you")), None)
        return (s["prompt"].endswith("Tap the lane you must use.") and len(boxes) >= 2 and {p["id"] for p in boxes} == {t["id"] for t in s["targets"]}
                and all(p["y"] == boxes[0]["y"] and p["w"] >= 54 and p["h"] >= 50 and "label" not in p for p in boxes) and all(0 <= g <= 10 for g in gaps)
                and all(t["label"].startswith("the ") and t["label"].endswith(" lane") for t in s["targets"])
                and s["highlight"] == s["answer"] and you is not None and abs(you["x"] - box["x"]) <= 4 and abs(you["y"] - box["y"]) <= 40
                and all(p["t"] != "lane" or p["id"] != s["answer"] for p in s["after"]))
    check(len(lanes) == 4 and all(lane_q(s) for s in lanes) and [s["fact"] for s in lanes] == ["c-010", "c-021", "b-136", "d-155"],
          "the four lane questions keep the one form, draw lane boxes side by side with nothing written in them, and put your car in the correct lane afterwards")
    slow = by_fact("c-010")[0]
    check(slow["answer"] == "right" and len([p for p in slow["parts"] if p["t"] == "lane"]) == 3 and next(p for p in slow["parts"] if p["t"] == "road").get("oneway") == 3
          and "slower" in slow["prompt"] and any(p["t"] == "shoulder" for p in slow["parts"]) and any(p["t"] == "median" for p in slow["parts"]),
          "the slower-traffic question draws three lanes one way between the median and the shoulder, and the right lane is the answer")
    decel = by_fact("c-021")[0]
    ramp_off = next((p for p in decel["parts"] if p["t"] == "ramp"), None)
    check(ramp_off is not None and ramp_off["kind"] == "off" and next(t["label"] for t in decel["targets"] if t["id"] == decel["answer"]) == "the deceleration lane"
          and "slow down" in decel["prompt"] and "deceleration lane" in decel["say"] and "deceleration lane" in decel["wrong"]["right"],
          "the exit question draws the off-ramp, and the deceleration lane is the answer, named in the explanation")
    over, slowed = by_fact("b-136")

    def stopped_on_shoulder(s):
        sh = next((p for p in s["parts"] if p["t"] == "shoulder"), None)
        em = [p for p in s["parts"] if p["t"] == "car" and p.get("emergency")]
        return sh is not None and len(em) == 1 and sh["x"] <= em[0]["x"] <= sh["x"] + sh["w"] and "emergency vehicle" in s["prompt"] and "flashing" in s["prompt"]
    check(over["kind"] == "tap" and over["answer"] == "left" and stopped_on_shoulder(over) and "left lane" in over["prompt"],
          "the Move Over question draws the emergency vehicle stopped on the shoulder with its lights flashing, says the left lane is clear, and the left lane is the answer")
    check(slowed["kind"] == "choose" and stopped_on_shoulder(slowed) and "slow down" in slowed["answer"] and "caution" in slowed["answer"]
          and any(p["t"] == "car" and p.get("color") == "blue" for p in slowed["parts"]) and "blue car" in slowed["prompt"],
          "the second Move Over question is a choice, with the blue car blocking the left lane, answered by slowing down with caution")
    work = by_fact("d-155")[0]
    check(work["answer"] == "left" and any(p["t"] == "cone" and p.get("to") and p.get("n", 0) >= 4 for p in work["parts"])
          and any(p["t"] == "roadsign" and p["kind"] == "diamond" and p["color"] == "orange" for p in work["parts"])
          and "closed" in work["prompt"] and "as soon as" in work["say"] and "as soon as" in work["wrong"]["right"],
          "the work zone question draws the orange diamond and a row of cones closing the right lane, the left lane is the answer, and the explanations say as soon as you see it")
    ramp = by_fact("c-004")[0]
    enter = by_fact("c-001")[0]
    check(ramp["kind"] == "tap" and ramp["prompt"].endswith("Who goes first? Tap the car.") and any(p["t"] == "ramp" and p["kind"] == "on" for p in ramp["parts"])
          and any(p["t"] == "car" and p.get("color") == "blue" and p.get("id") == ramp["answer"] for p in ramp["parts"]) and any(p["t"] == "path" for p in ramp["parts"])
          and ramp["highlight"] == ramp["answer"] and "yield" not in (ramp["say"] + ramp["wrong"]["you"]).lower(),
          "the ramp question asks who goes first with the on-ramp drawn, and the blue car on the interstate is the answer")
    check(enter["kind"] == "choose" and any(p["t"] == "ramp" and p["kind"] == "on" for p in enter["parts"]) and "speed up" in enter["answer"] and "merge" in enter["answer"]
          and enter["prompt"].count("merge") >= 2,
          "the entering question is a choice on the ramp, answered by speeding up and merging when the way is clear, with merge explained in the prompt")
    missed = by_fact("c-024")[0]
    check(missed["kind"] == "choose" and "next exit" in missed["answer"] and any(p["t"] == "ramp" and p["kind"] == "off" for p in missed["parts"])
          and any(p["t"] == "median" for p in missed["parts"]) and any(p["t"] == "shoulder" for p in missed["parts"])
          and all("next exit" in w for w in missed["wrong"].values()) and sum("illegal" in w for w in missed["wrong"].values()) >= 2,
          "the missed exit question is a choice with the exit behind you, the median and the shoulder drawn, answered by going on to the next exit")
    cross = by_fact("c-002")[0]
    check(cross["kind"] == "choose" and len([p for p in cross["parts"] if p["t"] == "road"]) == 3 and len([p for p in cross["parts"] if p["t"] == "median"]) == 2
          and "emergency vehicles and highway maintenance crews" in cross["answer"] and "crossover" in cross["prompt"],
          "the crossover question draws both roadways with a gap in the median, and only emergency vehicles and highway maintenance crews may use it")
    trouble = by_fact("c-035")[0]
    sh = next(p for p in trouble["parts"] if p["t"] == "shoulder")
    you_after = next(p for p in trouble["after"] if p["t"] == "car" and p.get("you"))
    check(trouble["kind"] == "choose" and "right shoulder" in trouble["answer"] and "flashers" in trouble["answer"] and sh["x"] <= you_after["x"] <= sh["x"] + sh["w"],
          "the car trouble question is a choice answered by the right shoulder and the flashers, and afterwards your car stands on the shoulder")
    alert = by_fact("c-003")[0]
    check(alert["kind"] == "choose" and "alertness" in alert["answer"] and "higher speed" in alert["prompt"], "the alertness question is a choice answered by constant alertness")
    check(steps[0]["fact"] == "c-001", "the first question is the entering choice")


def section_10(steps, facts):
    """Night, weather and emergencies."""
    check(all(s["fact"] for s in steps), "every question has a fact")
    check(all(all((p.get("color") == "red") == bool(p.get("you")) for p in s["parts"] if p["t"] == "car") for s in steps)
          and all(s["prompt"].startswith("You are the red car") for s in steps if any(p["t"] == "car" for p in s["parts"])),
          "every question with a car drawn says you are the red car, and only your car is red")
    by_fact = lambda f: [s for s in steps if s["fact"] == f]
    # Night: the tone is listed before the beams, your car has a beam, and the prompt says it is night.
    night = [s for s in steps if any(p["t"] == "night" for p in s["parts"])]

    def lit(s):
        kinds = [p["t"] for p in s["parts"]]
        you = next(p for p in s["parts"] if p["t"] == "car" and p.get("you"))
        return (kinds.index("night") < kinds.index("headlight") and "night" in s["prompt"]
                and any(p["t"] == "headlight" and p["x"] == you["x"] and p["y"] == you["y"] for p in s["parts"]))
    check(len(night) >= 3 and all(lit(s) for s in night), "every night question draws the night tone under a headlight beam from your car, and says it is night", len(night))
    see, compare = by_fact("c-042")
    beam = next(p for p in see["parts"] if p["t"] == "headlight")
    ped = next(p for p in see["parts"] if p["t"] == "ped")
    check(see["kind"] == "choose" and see["options"] == ["Yes", "No"] and see["answer"] == "No" and not beam.get("high") and ped["y"] < beam["y"] - 17 - 100
          and "person" in see["prompt"], "the first night question asks whether you can see the person past the end of your low beams, and the answer is No")
    check(compare["kind"] == "choose" and "more dangerous" in compare["answer"] and "headlights" in compare["answer"] and "daytime" in compare["prompt"],
          "the comparison question is answered by more dangerous, because your headlights limit how far you can see")
    when = by_fact("b-001")
    check(len(when) == 2 and all("30 minutes" in s["answer"] or (s["answer"] == "Yes" and "30 minutes" in s["say"]) for s in when)
          and any("30 minutes after sunset until 30 minutes before sunrise" in s["answer"] for s in when)
          and all("30 minutes" in w for s in when for w in s["wrong"].values()),
          "the headlight law is taught as 30 minutes after sunset until 30 minutes before sunrise, and every explanation says so")
    dim, follow = by_fact("c-050")
    oncoming = [p for p in dim["parts"] if p["t"] == "car" and not p.get("you")]
    near = max(oncoming, key=lambda p: p["y"])
    texts = {p["text"] for p in dim["parts"] if p["t"] == "measure"}
    check(dim["kind"] == "tap" and dim["prompt"].endswith("Tap the car.") and len(oncoming) == 2 and all(p["heading"] == "s" for p in oncoming) and dim["answer"] == near["id"]
          and texts == {"500 feet", "1,000 feet"} and "500 feet" in dim["prompt"] and "1,000 feet" in dim["prompt"] and dim["highlight"] == dim["answer"]
          and any(p["t"] == "headlight" and p.get("high") for p in dim["parts"]) and dim["after"] and not any(p.get("high") for p in dim["after"])
          and "500 feet" in dim["say"] and "1,000 feet" in dim["wrong"][next(p["id"] for p in oncoming if p is not near)],
          "the dimming question taps the car coming toward you within 500 feet, with 500 and 1,000 feet measured, and your high beam is dimmed afterwards")
    check(follow["kind"] == "choose" and follow["answer"] == "Yes" and "500 feet" in follow["prompt"] and any(p["t"] == "measure" and p["text"] == "500 feet" for p in follow["parts"])
          and any(p["t"] == "headlight" and p.get("high") for p in follow["parts"]) and follow["after"] and not any(p.get("high") for p in follow["after"]),
          "the following question is answered Yes at 500 feet, and your high beam is dimmed afterwards")
    fog = by_fact("c-043")[0]
    check(fog["kind"] == "choose" and "low beams" in fog["answer"] and "fog" in fog["prompt"], "the fog question is answered by the low beams")
    co = by_fact("a-032")[0]
    check(co["kind"] == "choose" and "no taste, no smell and no color" in co["answer"] and "cannot tell" in co["answer"], "the carbon monoxide question is answered by you cannot tell")
    hydro = by_fact("c-063")[0]
    check(hydro["kind"] == "choose" and "letting up on the gas" in hydro["answer"] and "hydroplane" in hydro["prompt"], "the hydroplaning question is answered by letting up on the gas")
    steer, brake = by_fact("b-045")
    boxes = sorted((p for p in steer["parts"] if p["t"] == "steer"), key=lambda p: p["x"])
    skid_car = next(p for p in steer["parts"] if p["t"] == "car" and p.get("you"))
    straight = next(p for p in steer["after"] if p["t"] == "car" and p.get("you"))
    check(steer["kind"] == "tap" and steer["prompt"].endswith("Tap the steering wheel.") and len(boxes) == 2 and {p["id"] for p in boxes} == {t["id"] for t in steer["targets"]}
          and boxes[0]["y"] == boxes[1]["y"] and all(p["w"] >= 140 and p["h"] >= 130 and "label" not in p for p in boxes) and 0 <= boxes[1]["x"] - boxes[0]["x"] - (boxes[0]["w"] + boxes[1]["w"]) / 2 <= 10
          and {p["turn"] for p in boxes} == {"left", "right"} and all(t["label"].startswith("the steering wheel turned to the ") for t in steer["targets"])
          and skid_car.get("tilt") and skid_car["heading"] == "n" and any(p["t"] == "path" for p in steer["parts"]) and "sliding to the left" in steer["prompt"]
          and steer["answer"] == "left" and steer["highlight"] == "left" and not straight.get("tilt") and not any(p["t"] == "path" for p in steer["after"])
          and len([p for p in steer["after"] if p["t"] == "steer"]) == 2,
          "the skid question taps one of two steering wheel pictures side by side with nothing written in them, the car tilted with its rear sliding left, and the car is straight afterwards")
    check(brake["kind"] == "choose" and "foot off the brake" in brake["answer"] and "brake" in brake["prompt"] and any(p.get("tilt") for p in brake["parts"] if p["t"] == "car"),
          "the brake question is a choice on the skidding car, answered by taking your foot off the brake")
    ice = by_fact("c-044")[0]
    check(ice["kind"] == "choose" and "locks the front wheels" in ice["answer"] and "steering" in ice["answer"] and "ice" in ice["prompt"], "the ice question is answered by locked front wheels and lost steering")
    flood = by_fact("c-075")[0]
    check(flood["kind"] == "choose" and "turn around" in flood["answer"] and any(p["t"] == "water" for p in flood["parts"]) and any(p["t"] == "label" and "water" in p["text"].lower() for p in flood["parts"])
          and "water" in flood["prompt"] and flood["after"] and any(p["t"] == "path" for p in flood["after"]) and all("turn around" in w for w in flood["wrong"].values()),
          "the flood question draws the water across the road and is answered by turning around, with the turn drawn afterwards")
    stall = by_fact("d-167")[0]
    rails = next(p for p in stall["parts"] if p["t"] == "rails")
    on_tracks = next(p for p in stall["parts"] if p["t"] == "car" and p.get("you"))
    check(stall["kind"] == "choose" and rails["y"] <= on_tracks["y"] <= rails["y"] + rails["h"] and any(p["t"] == "crossbuck" for p in stall["parts"]) and "stalled" in stall["prompt"]
          and "out of the car" in stall["answer"] and "away from the tracks" in stall["answer"] and stall["after"] and any(p["t"] == "ped" for p in stall["after"])
          and all("away from the tracks" in w for w in stall["wrong"].values()),
          "the stalled car question draws your car on the tracks and is answered by everyone getting out and away, with a person away from the tracks afterwards")
    check(steps[0] is see, "the first question is the night choice")


def section_11(steps, facts):
    """Alcohol and drugs."""
    check(all(s["fact"] for s in steps), "every question has a fact")
    check(all(s["kind"] == "choose" for s in steps), "every question is a choice, because no fact has exactly one correct thing to tap")
    check(not any(p["t"] in ("road", "car") for s in steps for p in s["parts"]), "nothing in the lesson is drawn on a road")
    by_fact = lambda f: [s for s in steps if s["fact"] == f]
    same = by_fact("c-126")[0]
    drinks = [p for p in same["parts"] if p["t"] == "drink"]
    check({p["kind"] for p in drinks} == {"beer", "shot"} and not any(p.get("alcohol") for p in drinks) and all(p.get("label", True) for p in drinks)
          and same["after"] and all(p.get("alcohol") for p in same["after"] if p["t"] == "drink") and "12 ounces" in same["prompt"] and "1 ounce" in same["prompt"]
          and "about the same" in same["answer"] and all("about the same" in w or "about as much" in w for w in same["wrong"].values()),
          "the drink question draws the beer and the shot with their sizes and nothing that answers it, says the sizes, and draws the alcohol in each afterwards")
    hours = by_fact("c-090")[0]
    line = next(p for p in hours["parts"] if p["t"] == "timeline")
    check(len([p for p in hours["parts"] if p["t"] == "drink" and p["kind"] == "beer"]) == 3 and not line.get("fill") and "three beers" in hours["prompt"] and "hour" in hours["prompt"]
          and "three hours" in hours["answer"] and hours["after"] and next(p for p in hours["after"] if p["t"] == "timeline")["fill"] == 3
          and all("three hours" in w for w in hours["wrong"].values()),
          "the hours question draws three beers over a timeline with nothing shaded, is answered by about three hours, and shades the band to 3 hours afterwards")
    sober = by_fact("c-096")[0]
    check("time" in sober["answer"].lower() and {o.lower().split()[0] for o in sober["options"] if o != sober["answer"]} >= {"drinking", "taking", "exercising"}
          and all("time" in w.lower() for w in sober["wrong"].values()), "the sobering question offers coffee, a cold shower and exercise, and is answered by time alone")
    bac = by_fact("c-091")[0]
    check("more intoxicated" in bac["answer"] and "BAC" in bac["prompt"], "the BAC question is answered by more intoxicated")
    skills = by_fact("c-093")[0]
    check(all(w in skills["answer"] for w in ("lertness", "oncentration", "eaction time", "oordination")), "the skills question is answered by all four skills")
    adult = by_fact("c-097")[0]
    young = by_fact("c-121")[0]
    check("21 or older" in adult["prompt"] and "0.08 percent" in adult["answer"] and {o for o in adult["options"] if o != adult["answer"]} == {"It is 0.10 percent.", "It is 0.15 percent.", "It is 0.20 percent."}
          and ("18" in young["prompt"] or "16 to 20" in young["prompt"]) and "0.02 percent" in young["answer"] and {o for o in young["options"] if o != young["answer"]} == {"It is 0.05 percent.", "It is 0.08 percent.", "It is 0.10 percent."},
          "the two BAC questions state the age and are answered by 0.08 percent at 21 and older and 0.02 percent at 16 to 20, with the test's other numbers")
    drugs = by_fact("c-089")[0]
    check("same" in drugs["answer"] and "prescri" in drugs["prompt"], "the drug question is about a prescribed drug and answered by the same penalty as for alcohol")
    consent = by_fact("c-092")
    check(len(consent) == 2 and consent[0]["answer"] == "Yes" and "Implied Consent" in consent[0]["say"] and "Implied Consent" in consent[1]["prompt"] and "agree to be tested" in consent[1]["answer"],
          "the Implied Consent law is used in a situation first, answered Yes, then named")
    altered = by_fact("c-134")
    check(len(altered) == 2 and altered[0]["answer"] == "Yes" and "altering" in altered[1]["answer"], "the altered license is asked as a situation first, answered Yes, then as the test asks it")
    check(steps[0] is same, "the first question is the drink choice")


def section_12(steps, facts):
    """Phones, seat belts, crashes and sharing the road."""
    check(all(s["fact"] for s in steps), "every question has a fact")
    check(all(all((p.get("color") == "red") == bool(p.get("you")) for p in s["parts"] if p["t"] == "car") for s in steps)
          and all(s["prompt"].startswith("You are the red car") for s in steps if any(p["t"] == "car" for p in s["parts"])),
          "every question with a car drawn says you are the red car, and only your car is red")
    check(not any(p["t"] in ("ped", "bicyclist") for s in steps for p in s["parts"] + (s["after"] or [])), "no person's body is drawn")
    by_fact = lambda f: [s for s in steps if s["fact"] == f]
    # The two seat questions: the cabin from above, three seats, the two passenger seats the targets, nothing written in them.
    taps = [s for s in steps if s["kind"] == "tap"]

    def cabin_ok(s):
        seats = [p for p in s["parts"] if p["t"] == "seat"]
        driver = [p for p in seats if p.get("wheel")]
        boxes = {p["id"]: p for p in seats if p.get("id")}
        return (s["parts"][0]["t"] == "cabin" and len(seats) == 3 and len(driver) == 1 and "id" not in driver[0] and set(boxes) == {"front-right", "back"}
                and set(boxes) == {t["id"] for t in s["targets"]} and all(p["w"] >= 68 and p["h"] >= 74 and "label" not in p and not p.get("belt") for p in seats)
                and boxes["front-right"]["y"] == driver[0]["y"] and boxes["back"]["y"] > boxes["front-right"]["y"]
                and {t["label"] for t in s["targets"]} == {"the front passenger seat", "the back seat"} and s["prompt"].startswith("You are driving.") and s["prompt"].endswith("Tap the seat."))
    check(len(taps) == 2 and all(cabin_ok(s) for s in taps) and {s["fact"] for s in taps} == {"a-044", "a-074"},
          "the two tap questions draw the cabin with the driver's seat, the front passenger seat and the back seat, the two passenger seats the targets, and ask which seat")
    belt, who = by_fact("a-044")
    check(belt["kind"] == "tap" and belt["answer"] == "front-right" and "25" in belt["prompt"] and "front passenger seat" in belt["prompt"] and "back seat" in belt["prompt"]
          and belt["after"] and {p.get("id", "driver") for p in belt["after"] if p["t"] == "seat" and p.get("belt")} == {"driver", "front-right"}
          and "18 or older" in belt["wrong"]["back"] and "front-seat passenger" in belt["wrong"]["back"],
          "the belt question taps the front passenger seat for a passenger who is 25, the belt is drawn on the front seats afterwards, and the back seat's explanation says why not")
    check(who["kind"] == "choose" and "driver and all front-seat passengers" in who["answer"] and "four times" in who["say"], "the test's own belt question is answered by the driver and all front-seat passengers")
    child = by_fact("a-074")[0]
    check(child["kind"] == "tap" and child["answer"] == "back" and "10 years old" in child["prompt"] and "air bags" in child["prompt"]
          and "12" in child["wrong"]["front-right"] and "air bag" in child["wrong"]["front-right"],
          "the child question taps the back seat for a child who is 10 in a car with air bags, and the front seat's explanation names the air bag")
    height, purpose = by_fact("a-002")[0], by_fact("a-001")[0]
    check(steps.index(height) < steps.index(purpose) and "back of your head" in height["answer"] and "whiplash" in purpose["answer"] and "from behind" in purpose["answer"]
          and {o for o in height["options"] if o != height["answer"]} == {"You set it level with the base of your neck.", "You set it level with the top of your shoulders.", "You set it just above the top of your head."},
          "the head restraint is set level with the back of the head first, then asked what it prevents when hit from behind, with the test's other heights")
    phone = by_fact("a-036")
    check(len(phone) == 2 and phone[0]["options"] == ["Yes", "No"] and phone[0]["answer"] == "No" and "shoulder" in phone[0]["prompt"] and "any part of" in phone[0]["say"]
          and phone[1]["answer"].startswith("Holding a phone with any part of your body"),
          "the Hands Free law is used on a phone held with the shoulder first, answered No, then asked as the test asks it")
    rear, forward = by_fact("a-050")
    check(rear["answer"] == "It must face the rear of the car." and "8 months" in rear["prompt"] and "17 pounds" in rear["prompt"] and "20 pounds" in rear["say"]
          and forward["answer"] == "It must face the front of the car." and "2 years" in forward["prompt"] and "28 pounds" in forward["prompt"] and "1 through 3" in forward["say"],
          "the car seat faces the rear for a child of 8 months and 17 pounds and the front for one of 2 years and 28 pounds, with the manual's 1 year and 20 pounds in the explanations")
    pregnant = by_fact("a-059")[0]
    check("below her belly" in pregnant["answer"] and "above her belly" in pregnant["answer"] and "abdomen" in pregnant["say"] and "pregnant" in pregnant["prompt"], "the pregnant woman's belt is lap belt below the belly, shoulder belt above it, and the explanation says the belly is the abdomen")
    stop, pass_by = by_fact("c-155")[0], by_fact("c-133")[0]
    cars = lambda s: [p for p in s["parts"] if p["t"] == "car"]
    you = lambda s: next(p for p in cars(s) if p.get("you"))
    check(stop["kind"] == "choose" and len(cars(stop)) == 2 and you(stop).get("tilt") and "hit the blue car" in stop["prompt"] and "without blocking traffic" in stop["answer"]
          and all("stop" in w for w in stop["wrong"].values()),
          "the crash question draws your car against the blue car and is answered by stopping at or near the scene without blocking traffic")
    police = [p for p in cars(pass_by) if p.get("emergency")]
    check(pass_by["kind"] == "choose" and len(cars(pass_by)) == 3 and len(police) == 1 and police[0]["color"] == "white" and "lights flashing" in pass_by["prompt"] and "not needed" in pass_by["prompt"]
          and "drive on slowly" in pass_by["answer"] and pass_by["after"] and any(p["t"] == "path" for p in pass_by["after"]),
          "the crash you pass draws the crashed car and the police car with its lights flashing, is answered by driving on slowly, and draws your way past afterwards")
    report = by_fact("c-132")[0]
    check(report["answer"] == "You have 20 days." and {o for o in report["options"] if o != report["answer"]} == {"You have 10 days.", "You have 48 hours.", "You have 30 days."}
          and "crash report" in report["prompt"] and all("20 days" in w for w in report["wrong"].values()),
          "the crash report is due in 20 days, with the test's other numbers, and every explanation says so")
    first = steps[0]
    check(first["kind"] == "choose" and not first["parts"], "the first question is a choice with nothing to draw")


# Section 3, the worked example, has no checks of its own beyond validate_data.py's.
CHECKS = {1: section_1, 2: section_2, 4: section_4, 5: section_5, 6: section_6, 7: section_7, 8: section_8,
          9: section_9, 10: section_10, 11: section_11, 12: section_12}


def main():
    for section, fn in CHECKS.items():
        print(f"\n[Section {section} lesson: {fn.__doc__.rstrip('.').lower()}]")
        try:
            fn(steps_of(section), SECTIONS[section])
        except (KeyError, IndexError, StopIteration, TypeError, ValueError) as e:
            check(False, f"the Section {section} checks stopped on data they could not read: {e!r}")
    print("\nAll checks passed." if not failures else f"\n{len(failures)} check(s) failed.")
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
