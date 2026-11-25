"""Blind benchmark of small logic-learning tasks from everyday domains.

Each task gives input predicates, answer predicates, the value constants a learner may use, and a REFERENCE rule program in
clingo-object notation. world_text(name, rnd, big) draws a random world; verify_worlds(name) enumerates every world of a small domain.
Kinds: a = one join or a constant test; b = negation, "two different" or two answer predicates; c = recursion or a helper under negation.
"""
from __future__ import annotations

import random

# --------------------------------------------------------------------------------------------------------------------------------
# world building: one builder per task, run either with a random picker or with an exhaustive enumerator (replay of choice sequences)
# --------------------------------------------------------------------------------------------------------------------------------


class _RandomPicker:
    def __init__(self, rnd: random.Random):
        self.rnd = rnd

    def pick(self, options, weights=None):
        return self.rnd.choices(options, weights=weights, k=1)[0]


class _EnumPicker:
    """Follows a fixed prefix of choice indices, then always takes option 0; records the size of every choice point."""

    def __init__(self, prefix):
        self.prefix = prefix
        self.sizes = []

    def pick(self, options, weights=None):
        i = len(self.sizes)
        k = self.prefix[i] if i < len(self.prefix) else 0
        self.sizes.append(len(options))
        return options[k]


class _World:
    def __init__(self, picker, p=0.5):
        self.picker = picker
        self.p = p  # probability of an optional fact in random mode (ignored when enumerating)
        self.facts: list[str] = []

    def pick(self, options, weights=None):
        return self.picker.pick(options, weights)

    def add(self, pred, *args):
        self.facts.append(f"{pred}({', '.join(args)})")

    def fixed(self, pred, xs):
        for x in xs:
            self.add(pred, x)

    def flag(self, pred, xs):
        for x in xs:
            if self.pick([False, True], [1 - self.p, self.p]):
                self.add(pred, x)

    def rel(self, pred, xs, ys, irreflexive=False):
        for x in xs:
            for y in ys:
                if irreflexive and x == y:
                    continue
                if self.pick([False, True], [1 - self.p, self.p]):
                    self.add(pred, x, y)

    def func(self, pred, xs, ys, optional=True, irreflexive=False):
        """Each x relates to at most one y (exactly one unless optional)."""
        for x in xs:
            opts = [y for y in ys if not (irreflexive and x == y)]
            if optional:
                opts = [None] + opts
                w = [1.0] + [1.0] * (len(opts) - 1)
            else:
                w = None
            y = self.pick(opts, w)
            if y is not None:
                self.add(pred, x, y)

    def attr(self, pred, xs, vals, optional=False):
        for x in xs:
            v = self.pick(([None] if optional else []) + list(vals))
            if v is not None:
                self.add(pred, x, v)


def _ents(prefix, n):
    return [f"{prefix}{i}" for i in range(1, n + 1)]


# --------------------------------------------------------------------------------------------------------------------------------
# builders: build(w, n, vals) — n is the size scale, vals the value lists (small, or extended by BIG_VALUES)
# --------------------------------------------------------------------------------------------------------------------------------

def _b_library_overdue(w, n, v):
    m, b = _ents("m", n), _ents("b", n)
    w.rel("loan", m, b)
    w.attr("book_status", b, v["status"])


def _b_kitchen_nut_label(w, n, v):
    d, i = _ents("d", n), _ents("i", n)
    w.rel("contains", d, i)
    w.attr("category", i, v["category"])


def _b_hospital_floor(w, n, v):
    p, wd, fl = _ents("p", n), _ents("w", n), _ents("fl", n)
    w.func("assigned", p, wd)
    w.func("ward_floor", wd, fl, optional=False)


def _b_traffic_must_stop(w, n, v):
    c, j = _ents("c", n), _ents("j", n)
    w.func("approaching", c, j)
    w.attr("light", j, v["light"])


def _b_school_passed(w, n, v):
    s, c = _ents("s", n), _ents("c", n)
    for x in s:
        for y in c:
            g = w.pick([None] + list(v["grade"]))
            if g is not None:
                w.add("grade", x, y, g)


def _b_bank_hold(w, n, v):
    t, a = _ents("t", n + 1), _ents("a", n)
    w.func("paid_to", t, a, optional=False)
    w.flag("flagged", a)


def _b_sports_available(w, n, v):
    p = _ents("p", n)
    w.flag("in_squad", p)
    w.attr("fitness", p, v["fitness"])


def _b_garden_needs_water(w, n, v):
    p, b = _ents("p", n), _ents("b", n)
    w.func("planted_in", p, b, optional=False)
    w.attr("soil", b, v["soil"])


def _b_office_projector(w, n, v):
    m, r = _ents("m", n), _ents("r", n)
    w.func("held_in", m, r, optional=False)
    w.rel("equipped", r, v["equipment"])


def _b_logistics_express(w, n, v):
    p, r = _ents("p", n + 1), _ents("r", n)
    w.func("on_route", p, r, optional=False)
    w.attr("route_mode", r, v["mode"])


def _b_family_grandparent(w, n, v):
    p = _ents("p", n)
    w.rel("parent", p, p, irreflexive=True)


def _b_library_lendable(w, n, v):
    b = _ents("b", n)
    w.fixed("book", b)
    w.flag("reserved", b)
    w.flag("damaged", b)


def _b_school_classmates(w, n, v):
    s, c = _ents("s", n + 1), _ents("c", n)
    w.rel("enrolled", s, c)


def _b_hospital_triage(w, n, v):
    p = _ents("p", n)
    w.flag("admitted", p)
    w.attr("condition", p, v["condition"])


def _b_kitchen_pan_clash(w, n, v):
    d, p = _ents("d", n + 1), _ents("pan", n)
    w.func("uses_pan", d, p)


def _b_traffic_red_light(w, n, v):
    c, j = _ents("c", n), _ents("j", n)
    w.func("crossed", c, j)
    w.attr("signal", j, v["signal"])
    w.flag("emergency", c)


def _b_bank_loan(w, n, v):
    l, a = _ents("l", n), _ents("a", n)
    w.func("applied_by", l, a, optional=False)
    w.attr("credit", a, v["credit"])
    w.flag("blacklisted", a)


def _b_sports_results(w, n, v):
    m, t = _ents("m", n), _ents("t", n + 1)
    pairs = [(x, y) for x in t for y in t if x != y]
    for x in m:
        h, a = w.pick(pairs)
        w.add("home", x, h)
        w.add("away", x, a)
    w.attr("result", m, v["result"])


def _b_garden_crowded(w, n, v):
    p, b = _ents("p", n + 1), _ents("b", n)
    w.func("in_bed", p, b)


def _b_office_signoff(w, n, v):
    r, e = _ents("r", n + 1), _ents("e", n)
    w.func("filed_by", r, e)
    w.flag("manager", e)


_RPS_BEATS = [("rock", "scissors"), ("paper", "rock"), ("scissors", "paper"),
              ("rock", "lizard"), ("paper", "spock"), ("scissors", "lizard"),
              ("lizard", "spock"), ("lizard", "paper"), ("spock", "scissors"), ("spock", "rock")]


def _b_games_rps(w, n, v):
    p = _ents("pl", n)
    for x, y in _RPS_BEATS:
        if x in v["hand"] and y in v["hand"]:
            w.add("beats", x, y)
    w.attr("throws", p, v["hand"], optional=True)


def _b_logistics_cold_chain(w, n, v):
    s, t = _ents("s", n), _ents("t", n)
    w.func("loaded_on", s, t, optional=False)
    w.attr("cargo", s, v["cargo"])
    w.flag("refrigerated", t)


def _b_family_ancestor(w, n, v):
    p = _ents("p", n)
    for child in p:  # each child has at most one recorded parent
        par = w.pick([None] + [x for x in p if x != child])
        if par is not None:
            w.add("parent_of", par, child)


def _b_logistics_served(w, n, v):
    c = _ents("c", n)
    w.add("depot", c[0])
    w.func("road", c, c, irreflexive=True)


def _b_office_top_manager(w, n, v):
    e = _ents("e", n)
    w.fixed("employee", e)
    w.func("reports_to", e, e, irreflexive=True)


def _b_kitchen_vegetarian(w, n, v):
    d, i = _ents("d", n), _ents("i", n)
    w.fixed("dish", d)
    w.rel("made_with", d, i)
    w.attr("food_kind", i, v["food_kind"])


def _b_school_eligible(w, n, v):
    s, c = _ents("s", max(1, n - 2)), _ents("c", n)
    w.fixed("student", s)
    w.fixed("course", c)
    w.func("requires", c, c, irreflexive=True)
    w.rel("has_passed", s, c)


def _b_hospital_exposure(w, n, v):
    p = _ents("p", n)
    w.add("positive", p[0])
    w.func("contact", p, p, irreflexive=True)


def _b_traffic_gridlock(w, n, v):
    j = _ents("j", n)
    w.func("blocks", j, j, irreflexive=True)


def _b_bank_fraud(w, n, v):
    a = _ents("a", n)
    w.func("transfer", a, a, irreflexive=True)
    w.flag("watchlisted", a)


def _b_garden_irrigation(w, n, v):
    b = _ents("b", n)
    w.fixed("bed", b)
    w.add("source", b[0])
    w.func("flows_to", b, b, irreflexive=True)


def _b_sports_ranking(w, n, v):
    t = _ents("t", n)
    w.rel("beat", t, t, irreflexive=True)


def _b_games_levels(w, n, v):
    lv = _ents("l", n)
    w.add("start", lv[0])
    w.func("unlocks", lv, lv, irreflexive=True)
    w.flag("completed", lv)


# --------------------------------------------------------------------------------------------------------------------------------
# the tasks
# --------------------------------------------------------------------------------------------------------------------------------

_SPECS = [
    # ---- kind a: one join or a constant test ----
    dict(name="library_overdue", kind="a", build=_b_library_overdue, n=2,
         domain="A library notifies every member who has a book on loan whose status is overdue.",
         inputs={"loan": 2, "book_status": 2}, answers={"notify": 1},
         values={"status": ["overdue", "on_time"]}, big={"status": ["lost"]},
         REFERENCE="notify(M) <= loan(M, B) & book_status(B, overdue)"),
    dict(name="kitchen_nut_label", kind="a", build=_b_kitchen_nut_label, n=2,
         domain="A kitchen labels every dish that contains an ingredient of category nut.",
         inputs={"contains": 2, "category": 2}, answers={"nut_warning": 1},
         values={"category": ["nut", "dairy", "grain"]}, big={"category": ["fruit"]},
         REFERENCE="nut_warning(D) <= contains(D, I) & category(I, nut)"),
    dict(name="hospital_floor", kind="a", build=_b_hospital_floor, n=2,
         domain="A hospital derives on which floor each patient lies from the patient's ward and the ward's floor.",
         inputs={"assigned": 2, "ward_floor": 2}, answers={"patient_floor": 2},
         values={}, big={},
         REFERENCE="patient_floor(P, F) <= assigned(P, W) & ward_floor(W, F)"),
    dict(name="traffic_must_stop", kind="a", build=_b_traffic_must_stop, n=2,
         domain="A car must stop when the junction it is approaching shows a red light.",
         inputs={"approaching": 2, "light": 2}, answers={"must_stop": 1},
         values={"light": ["red", "green", "amber"]}, big={"light": ["flashing"]},
         REFERENCE="must_stop(C) <= approaching(C, J) & light(J, red)"),
    dict(name="school_passed", kind="a", build=_b_school_passed, n=2,
         domain="A school lists which student passed which course from the recorded grade.",
         inputs={"grade": 3}, answers={"passed": 2},
         values={"grade": ["passing", "failing"]}, big={"grade": ["incomplete"]},
         REFERENCE="passed(S, C) <= grade(S, C, passing)"),
    dict(name="bank_hold", kind="a", build=_b_bank_hold, n=2,
         domain="A bank holds every transaction paid to a flagged account.",
         inputs={"paid_to": 2, "flagged": 1}, answers={"hold": 1},
         values={}, big={},
         REFERENCE="hold(T) <= paid_to(T, A) & flagged(A)"),
    dict(name="sports_available", kind="a", build=_b_sports_available, n=3,
         domain="A coach can field a player who is in the squad and whose fitness is fit.",
         inputs={"in_squad": 1, "fitness": 2}, answers={"available": 1},
         values={"fitness": ["fit", "injured", "suspended"]}, big={"fitness": ["doubtful"]},
         REFERENCE="available(P) <= in_squad(P) & fitness(P, fit)"),
    dict(name="garden_needs_water", kind="a", build=_b_garden_needs_water, n=2,
         domain="A gardener waters every plant whose bed has dry soil.",
         inputs={"planted_in": 2, "soil": 2}, answers={"needs_water": 1},
         values={"soil": ["dry", "moist", "wet"]}, big={"soil": ["frozen"]},
         REFERENCE="needs_water(P) <= planted_in(P, B) & soil(B, dry)"),
    dict(name="office_projector", kind="a", build=_b_office_projector, n=2,
         domain="A meeting can show slides when its room is equipped with a projector.",
         inputs={"held_in": 2, "equipped": 2}, answers={"can_present": 1},
         values={"equipment": ["projector", "whiteboard"]}, big={"equipment": ["screen"]},
         REFERENCE="can_present(M) <= held_in(M, R) & equipped(R, projector)"),
    dict(name="logistics_express", kind="a", build=_b_logistics_express, n=2,
         domain="A parcel is express when the route it travels on goes by air.",
         inputs={"on_route": 2, "route_mode": 2}, answers={"express": 1},
         values={"mode": ["air", "road", "sea"]}, big={"mode": ["rail"]},
         REFERENCE="express(P) <= on_route(P, R) & route_mode(R, air)"),
    dict(name="family_grandparent", kind="a", build=_b_family_grandparent, n=3,
         domain="A family tree derives grandparents as parents of a parent.",
         inputs={"parent": 2}, answers={"grandparent": 2},
         values={}, big={},
         REFERENCE="grandparent(G, C) <= parent(G, P) & parent(P, C)"),

    # ---- kind b: negation, two different, two answer predicates ----
    dict(name="library_lendable", kind="b", build=_b_library_lendable, n=3,
         domain="A library may lend a book that is neither reserved nor damaged.",
         inputs={"book": 1, "reserved": 1, "damaged": 1}, answers={"lendable": 1},
         values={}, big={},
         REFERENCE="lendable(B) <= book(B) & ~reserved(B) & ~damaged(B)"),
    dict(name="school_classmates", kind="b", build=_b_school_classmates, n=2,
         domain="Two different students enrolled in the same course are classmates.",
         inputs={"enrolled": 2}, answers={"classmates": 2},
         values={}, big={},
         REFERENCE="classmates(A, B) <= enrolled(A, C) & enrolled(B, C) & (A != B)"),
    dict(name="hospital_triage", kind="b", build=_b_hospital_triage, n=3,
         domain="An admitted patient in critical condition goes to intensive care; an admitted stable one is discharged.",
         inputs={"admitted": 1, "condition": 2}, answers={"icu": 1, "discharge": 1},
         values={"condition": ["critical", "stable", "serious"]}, big={"condition": ["recovering"]},
         REFERENCE="icu(P) <= admitted(P) & condition(P, critical)\n"
                   "discharge(P) <= admitted(P) & condition(P, stable)"),
    dict(name="kitchen_pan_clash", kind="b", build=_b_kitchen_pan_clash, n=2,
         domain="Two different dishes planned for the same pan clash.",
         inputs={"uses_pan": 2}, answers={"pan_clash": 2},
         values={}, big={},
         REFERENCE="pan_clash(D, E) <= uses_pan(D, P) & uses_pan(E, P) & (D != E)"),
    dict(name="traffic_red_light", kind="b", build=_b_traffic_red_light, n=2,
         domain="A car that crossed a junction while its signal was red ran a red light, unless it is an emergency vehicle.",
         inputs={"crossed": 2, "signal": 2, "emergency": 1}, answers={"ran_red": 1},
         values={"signal": ["red", "green"]}, big={"signal": ["amber"]},
         REFERENCE="ran_red(C) <= crossed(C, J) & signal(J, red) & ~emergency(C)"),
    dict(name="bank_loan", kind="b", build=_b_bank_loan, n=2,
         domain="A loan is approved when its applicant has good credit and is not blacklisted, and rejected when the credit is poor.",
         inputs={"applied_by": 2, "credit": 2, "blacklisted": 1}, answers={"approve": 1, "reject": 1},
         values={"credit": ["good", "poor"]}, big={"credit": ["unrated"]},
         REFERENCE="approve(L) <= applied_by(L, A) & credit(A, good) & ~blacklisted(A)\n"
                   "reject(L) <= applied_by(L, A) & credit(A, poor)"),
    dict(name="sports_results", kind="b", build=_b_sports_results, n=2,
         domain="From each match's home team, away team and result, a league derives which teams won and which lost a match.",
         inputs={"home": 2, "away": 2, "result": 2}, answers={"won": 1, "lost": 1},
         values={"result": ["home_win", "away_win", "draw"]}, big={"result": ["abandoned"]},
         REFERENCE="won(T) <= home(M, T) & result(M, home_win)\n"
                   "won(T) <= away(M, T) & result(M, away_win)\n"
                   "lost(T) <= home(M, T) & result(M, away_win)\n"
                   "lost(T) <= away(M, T) & result(M, home_win)"),
    dict(name="garden_crowded", kind="b", build=_b_garden_crowded, n=2,
         domain="A bed is crowded when two different plants grow in it.",
         inputs={"in_bed": 2}, answers={"crowded": 1},
         values={}, big={},
         REFERENCE="crowded(B) <= in_bed(P, B) & in_bed(Q, B) & (P != Q)"),
    dict(name="office_signoff", kind="b", build=_b_office_signoff, n=2,
         domain="An expense request filed by a manager is approved automatically; one filed by anyone else needs a sign-off.",
         inputs={"filed_by": 2, "manager": 1}, answers={"auto_approved": 1, "needs_signoff": 1},
         values={}, big={},
         REFERENCE="auto_approved(R) <= filed_by(R, E) & manager(E)\n"
                   "needs_signoff(R) <= filed_by(R, E) & ~manager(E)"),
    dict(name="games_rps", kind="b", build=_b_games_rps, n=3,
         domain="In a hand game a player wins against another whose throw is beaten by theirs; two different players with the same throw draw.",
         inputs={"throws": 2, "beats": 2}, answers={"wins": 2, "draw": 2},
         values={"hand": ["rock", "paper", "scissors"]}, big={"hand": ["lizard", "spock"]},
         REFERENCE="wins(P, Q) <= throws(P, X) & throws(Q, Y) & beats(X, Y)\n"
                   "draw(P, Q) <= throws(P, X) & throws(Q, X) & (P != Q)"),
    dict(name="logistics_cold_chain", kind="b", build=_b_logistics_cold_chain, n=2,
         domain="Frozen cargo loaded on a truck that is not refrigerated is at risk of spoiling.",
         inputs={"loaded_on": 2, "cargo": 2, "refrigerated": 1}, answers={"spoil_risk": 1},
         values={"cargo": ["frozen", "dry"]}, big={"cargo": ["chilled"]},
         REFERENCE="spoil_risk(S) <= cargo(S, frozen) & loaded_on(S, T) & ~refrigerated(T)"),

    # ---- kind c: recursion or a helper under negation ----
    dict(name="family_ancestor", kind="c", build=_b_family_ancestor, n=4,
         domain="A family tree derives every ancestor of a person through any number of parent steps.",
         inputs={"parent_of": 2}, answers={"ancestor": 2},
         values={}, big={},
         REFERENCE="ancestor(A, D) <= parent_of(A, D)\n"
                   "ancestor(A, D) <= parent_of(A, X) & ancestor(X, D)"),
    dict(name="logistics_served", kind="c", build=_b_logistics_served, n=4,
         domain="A city is served when a truck can reach it from a depot along one-way roads.",
         inputs={"depot": 1, "road": 2}, answers={"served": 1},
         values={}, big={},
         REFERENCE="served(C) <= depot(D) & road(D, C)\n"
                   "served(C) <= served(B) & road(B, C)"),
    dict(name="office_top_manager", kind="c", build=_b_office_top_manager, n=3,
         domain="An employee who reports to nobody is a top manager.",
         inputs={"employee": 1, "reports_to": 2}, answers={"top_manager": 1},
         values={}, big={},
         REFERENCE="has_boss(E) <= reports_to(E, M)\n"
                   "top_manager(E) <= employee(E) & ~has_boss(E)"),
    dict(name="kitchen_vegetarian", kind="c", build=_b_kitchen_vegetarian, n=2,
         domain="A dish is vegetarian when none of its ingredients is meat.",
         inputs={"dish": 1, "made_with": 2, "food_kind": 2}, answers={"vegetarian": 1},
         values={"food_kind": ["meat", "vegetable"]}, big={"food_kind": ["grain"]},
         REFERENCE="has_meat(D) <= made_with(D, I) & food_kind(I, meat)\n"
                   "vegetarian(D) <= dish(D) & ~has_meat(D)"),
    dict(name="school_eligible", kind="c", build=_b_school_eligible, n=3,
         domain="A student may take a course when every course it requires has been passed by the student.",
         inputs={"student": 1, "course": 1, "requires": 2, "has_passed": 2}, answers={"eligible": 2},
         values={}, big={},
         REFERENCE="blocked(S, C) <= student(S) & requires(C, P) & ~has_passed(S, P)\n"
                   "eligible(S, C) <= student(S) & course(C) & ~blocked(S, C)"),
    dict(name="hospital_exposure", kind="c", build=_b_hospital_exposure, n=4,
         domain="A person is exposed when a chain of contacts leads to them from someone who tested positive.",
         inputs={"positive": 1, "contact": 2}, answers={"exposed": 1},
         values={}, big={},
         REFERENCE="exposed(P) <= positive(Q) & contact(Q, P)\n"
                   "exposed(P) <= exposed(Q) & contact(Q, P)"),
    dict(name="traffic_gridlock", kind="c", build=_b_traffic_gridlock, n=4,
         domain="A junction is deadlocked when the chain of junctions it blocks leads back to itself.",
         inputs={"blocks": 2}, answers={"deadlocked": 1},
         values={}, big={},
         REFERENCE="waits_on(A, B) <= blocks(A, B)\n"
                   "waits_on(A, C) <= waits_on(A, B) & blocks(B, C)\n"
                   "deadlocked(J) <= waits_on(J, J)"),
    dict(name="bank_fraud", kind="c", build=_b_bank_fraud, n=3,
         domain="An account is suspicious when money from it reaches a watchlisted account through a chain of transfers.",
         inputs={"transfer": 2, "watchlisted": 1}, answers={"suspicious": 1},
         values={}, big={},
         REFERENCE="reaches(A, B) <= transfer(A, B)\n"
                   "reaches(A, C) <= reaches(A, B) & transfer(B, C)\n"
                   "suspicious(A) <= reaches(A, B) & watchlisted(B)"),
    dict(name="garden_irrigation", kind="c", build=_b_garden_irrigation, n=4,
         domain="Water runs from the source bed along channels; a bed the water never reaches stays dry.",
         inputs={"bed": 1, "source": 1, "flows_to": 2}, answers={"dry": 1},
         values={}, big={},
         REFERENCE="watered(B) <= source(B)\n"
                   "watered(B) <= watered(A) & flows_to(A, B)\n"
                   "dry(B) <= bed(B) & ~watered(B)"),
    dict(name="sports_ranking", kind="c", build=_b_sports_ranking, n=3,
         domain="A team outranks every team it beat directly or through a chain of wins; a team that won a game and never lost is unbeaten.",
         inputs={"beat": 2}, answers={"outranks": 2, "unbeaten": 1},
         values={}, big={},
         REFERENCE="outranks(A, B) <= beat(A, B)\n"
                   "outranks(A, C) <= beat(A, B) & outranks(B, C)\n"
                   "has_lost(T) <= beat(X, T)\n"
                   "unbeaten(T) <= beat(T, X) & ~has_lost(T)"),
    dict(name="games_levels", kind="c", build=_b_games_levels, n=3,
         domain="A level is unlocked from the start level by completing levels that unlock the next; an unlocked level not yet completed is next up.",
         inputs={"start": 1, "unlocks": 2, "completed": 1}, answers={"next_up": 1},
         values={}, big={},
         REFERENCE="unlocked(L) <= start(L)\n"
                   "unlocked(L) <= unlocked(K) & completed(K) & unlocks(K, L)\n"
                   "next_up(L) <= unlocked(L) & ~completed(L)"),
]

_BY_NAME = {s["name"]: s for s in _SPECS}

TASKS = {s["name"]: {"domain": s["domain"], "inputs": dict(s["inputs"]), "answers": dict(s["answers"]),
                     "constants": [c for vals in s["values"].values() for c in vals], "REFERENCE": s["REFERENCE"]}
         for s in _SPECS}

#: kind per task: a (one join / constant test), b (negation, two different, two answers), c (recursion / helper under negation)
KINDS = {s["name"]: s["kind"] for s in _SPECS}

#: value constants that occur only in big worlds (the learner never sees them in small worlds)
BIG_ONLY_CONSTANTS = {s["name"]: [c for vals in s["big"].values() for c in vals] for s in _SPECS}


def _values(spec, big):
    vals = {k: list(v) for k, v in spec["values"].items()}
    if big:
        for k, extra in spec["big"].items():
            vals[k] = vals.get(k, []) + list(extra)
    return vals


def _text(facts):
    return "\n".join(sorted(set(facts)))


def world_text(name: str, rnd: random.Random, big: bool = False) -> str:
    """A random world of task `name` as fact lines. big=True: more entities and the value constants that small worlds never use."""
    spec = _BY_NAME[name]
    n0 = spec["n"]
    n = rnd.randint(n0 + 3, n0 + 6) if big else rnd.randint(max(2, n0 - 1), n0 + 1)
    p = min(0.5, 1.5 / n) if big else 0.5
    w = _World(_RandomPicker(rnd), p=p)
    spec["build"](w, n, _values(spec, big))
    return _text(w.facts)


def verify_worlds(name: str) -> list[str]:
    """Every world of the small verification domain of task `name`, enumerated exhaustively."""
    spec = _BY_NAME[name]
    vals = _values(spec, False)
    seen, out = set(), []
    prefix: list[int] = []
    while True:
        picker = _EnumPicker(prefix)
        w = _World(picker)
        spec["build"](w, spec["n"], vals)
        t = _text(w.facts)
        if t not in seen:
            seen.add(t)
            out.append(t)
        sizes = picker.sizes
        choice = prefix + [0] * (len(sizes) - len(prefix))
        j = len(sizes) - 1
        while j >= 0 and choice[j] + 1 >= sizes[j]:
            j -= 1
        if j < 0:
            return out
        prefix = choice[:j] + [choice[j] + 1]
