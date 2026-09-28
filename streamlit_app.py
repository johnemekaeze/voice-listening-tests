"""Pairwise listening test: Mansa against each other system, two voices at a time.

Each trial is one script read by a Mansa voice and by one other system's voice from the same
round (same language, variant and voice gender). Listeners hear Voice A and Voice B and pick the
better one on naturalness, intelligibility, pronunciation and overall, then say why.

Blindness: pairs are built here on the server from the private clip key, so the browser only
ever gets two anonymous audio files. Which side Mansa is on is randomised per listener and pair,
and trials from different rounds are interleaved so the same voice does not recur back to back.
Pairs with the fewest judgments so far are served first, so coverage stays even when people stop
early.

    streamlit run streamlit_app.py
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

import streamlit as st

import common as C
import store

MANSA = "Mansa"
TITLE = "Voice Pairs"
CHOICES = ["A", "B", "Same"]
CHOICE_LABEL = {"A": "Voice A", "B": "Voice B", "Same": "About the same"}
QUESTIONS = [
    ("naturalness", "Which sounds more natural?", "More like a real person talking."),
    ("intelligibility", "Which is easier to understand?", "Every word clear without effort."),
    ("pronunciation", "Which pronounces the words better?",
     "Words, tones, names and numbers said correctly for this language or accent."),
    ("overall", "Overall, which is better?", "The one you would rather use."),
]
MIN_REASON = 8
S = C.S


# --------------------------------------------------------------------------- data
@st.cache_resource(show_spinner=False)
def get_store():
    return store.open_store(store.PAIRS_SHEET, store.PAIR_COLUMNS, "pairwise_local.csv")


@st.cache_data(ttl=900, show_spinner=False)
def clip_key() -> dict:
    return get_store().key()


@st.cache_data(ttl=900, show_spinner=False)
def all_pairs() -> dict:
    """Every Mansa clip against every other system's clip in the same round."""
    key, pairs = clip_key(), {}
    for r in C.ROUNDS:
        ids = [c["id"] for c in r["clips"] if c["id"] in key]
        mansa = [c for c in ids if key[c]["system"] == MANSA]
        for m in mansa:
            for o in ids:
                if key[o]["system"] != MANSA:
                    pid = f"{m}~{o}"
                    pairs[pid] = {"id": pid, "round": r["id"], "mansa": m, "other": o}
    return pairs


def sides(p: dict) -> tuple[str, str]:
    """(clip on A, clip on B), fixed per listener and pair so a returning listener sees the same."""
    mansa_first = C.rank(f"{S.lid}|{p['id']}|side") % 2 == 0
    return (p["mansa"], p["other"]) if mansa_first else (p["other"], p["mansa"])


def pairs_in(group: str) -> int:
    return sum(1 for p in all_pairs().values() if C.BY_ID[p["round"]]["group"] == group)


def init_state() -> None:
    S.setdefault("view", "intro")
    S.setdefault("name", "")
    S.setdefault("lid", "")
    S.setdefault("langs", {"english": "fluent"})
    S.setdefault("status", {})   # pair id -> "rated" | "skipped"
    S.setdefault("saved", {})    # pair id -> {criterion: "A"|"B"|"Same", "note": text}
    S.setdefault("queue", [])
    S.setdefault("current", None)
    S.setdefault("scroll", 0)


def done_count() -> int:
    return sum(1 for pid in S.queue if pid in S.status)


def next_open(after: str | None = None) -> str | None:
    i = S.queue.index(after) if after in S.queue else -1
    for pid in S.queue[i + 1:] + S.queue[:i + 1]:
        if pid not in S.status:
            return pid
    return None


def go(view: str, pid: str | None = None) -> None:
    S.view = view
    if pid:
        S.current = pid
    S.pop("pair_error", None)
    S.scroll += 1


def build_queue(counts: Counter) -> None:
    """Least-judged pairs first (random among equals), then spread so rounds don't repeat back to back."""
    cand = [p for p in all_pairs().values() if C.BY_ID[p["round"]]["group"] in S.langs]
    cand.sort(key=lambda p: (counts.get(p["id"], 0), C.rank(f"{S.lid}|{p['id']}")))
    out = []
    while cand:
        prev = out[-1]["round"] if out else None
        i = next((k for k, p in enumerate(cand[:12]) if p["round"] != prev), 0)
        out.append(cand.pop(i))
    S.queue = [p["id"] for p in out]


# --------------------------------------------------------------------------- actions
def start() -> None:
    name = C.clean_name(S.get("name_input", ""))
    langs = C.chosen_levels()
    if not name:
        S.intro_error = "Type your name so we can tell listeners apart."
        return
    if not langs:
        S.intro_error = "Choose at least one language you can judge."
        return
    if not all_pairs():
        S.intro_error = "The test isn't set up yet (no answer key), so there are no pairs to play. Tell the organiser."
        return
    S.pop("intro_error", None)
    lid = C.listener_id(name)
    counts: Counter = Counter()
    try:
        rows = get_store().rows()
        counts = Counter(r["pair_id"] for r in rows if r.get("skipped") != "yes")
        if lid != S.lid:
            S.status, S.saved = {}, {}
            for r in rows:
                if r.get("listener_id") != lid or r.get("pair_id") not in all_pairs():
                    continue
                S.status[r["pair_id"]] = "skipped" if r.get("skipped") == "yes" else "rated"
                S.saved[r["pair_id"]] = {c: r.get(col) for c, col in store.PAIR_CHOICE_COLUMNS.items()
                                         if r.get(col) in CHOICES}
                if r.get(store.PAIR_NOTES):
                    S.saved[r["pair_id"]]["note"] = r[store.PAIR_NOTES]
    except Exception as exc:  # a failed read must not block a new listener
        S.store_error = f"Couldn't load earlier answers: {exc}"
    S.name, S.lid, S.langs = name, lid, langs
    build_queue(counts)
    nxt = next_open()
    go("pair", nxt) if nxt else go("done")


def submit(pid: str, skip: bool) -> None:
    p = all_pairs()[pid]
    if not skip:
        missing = [q for crit, q, _ in QUESTIONS if S.get(f"{pid}|{crit}") is None]
        note = (S.get(f"{pid}|note") or "").strip()
        if missing:
            S.pair_error = "Still to answer: " + "; ".join(missing)
            return
        if len(note) < MIN_REASON:
            S.pair_error = "Say briefly why: what made the better voice better, or what went wrong in the other."
            return
    a, b = sides(p)
    mansa_side = "A" if a == p["mansa"] else "B"
    key, r = clip_key(), C.BY_ID[p["round"]]
    row = {
        "saved_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "listener_name": S.name, "listener_id": S.lid,
        "language": C.GROUP_NAME[r["group"]], "level": C.LEVELS[S.langs.get(r["group"], "fluent")],
        "round_id": p["round"], "round": r["title"], "voice_gender": r["gender"],
        "pair_id": pid, "voice_a_clip": a, "voice_b_clip": b, "mansa_is": mansa_side,
        "competitor": key[p["other"]]["system"], "competitor_voice": key[p["other"]]["voice"],
        "mansa_voice": key[p["mansa"]]["voice"],
        "skipped": "yes" if skip else "", "row_key": f"{S.lid}|{pid}",
    }
    saved = {}
    for crit, _, _ in QUESTIONS:
        choice = None if skip else S.get(f"{pid}|{crit}")
        row[store.PAIR_CHOICE_COLUMNS[crit]] = choice or ""
        row[store.PAIR_SCORE_COLUMNS[crit]] = ("" if choice is None else
                                               0.5 if choice == "Same" else 1 if choice == mansa_side else 0)
        if choice:
            saved[crit] = choice
    note = "" if skip else (S.get(f"{pid}|note") or "").strip()
    row[store.PAIR_NOTES] = note
    if note:
        saved["note"] = note
    try:
        get_store().upsert([row])
    except Exception as exc:
        S.pair_error = f"Not saved. Check your connection and press Save again. ({exc})"
        return
    S.status[pid] = "skipped" if skip else "rated"
    S.saved[pid] = saved
    nxt = next_open(pid)
    go("pair", nxt) if nxt else go("done")


# --------------------------------------------------------------------------- views
def top_bar() -> None:
    C.top_bar(TITLE, f"{S.name} · {done_count()} of {len(S.queue)} pairs saved", done_count(), len(S.queue),
              go, "All pairs")


def view_intro() -> None:
    returning = bool(S.status)
    C.hero("Listening panel", "Welcome back." if returning else "Two voices. Pick the better one.",
           "Each trial plays the same line read by two text-to-speech systems. Their names are hidden and "
           "the order is shuffled. Listen to both, pick the better one on each question, and say why.")
    C.steps("Enter your name and languages", "Play Voice A and Voice B", "Pick the better one and say why")
    C.section("What you'll be asked")
    C.guide([(q, h) for _, q, h in QUESTIONS],
            '<div class="legend"><span>Choose <b>Voice A</b>, <b>Voice B</b> or <b>About the same</b> '
            'for each question.</span></div>')
    C.section("About you")
    C.name_input()
    C.section("Languages you can judge")
    chosen = C.language_picker(lambda g: f"{pairs_in(g)} pairs")
    n = sum(pairs_in(g) for g in chosen)
    if S.get("intro_error"):
        st.error(S.intro_error)
    c1, c2 = st.columns([1.4, 3], vertical_alignment="center")
    c1.button("Continue listening" if returning else "Start listening", type="primary", on_click=start,
              width="stretch")
    c2.caption("Choose at least one language." if not chosen
               else "No pairs are set up for these languages yet." if not n
               else f"{n} pairs, about {max(3, round(n * 0.75))} minutes for all of them. Answers save after every "
                    "pair, so do as many as you can and stop any time.")
    C.store_notice(get_store())


def view_pair() -> None:
    top_bar()
    pid = S.current
    p = all_pairs()[pid]
    r = C.BY_ID[p["round"]]
    a, b = sides(p)
    pos = S.queue.index(pid) + 1 if pid in S.queue else 0
    C.script_block(r, f"Pair {pos} of {len(S.queue)} · {C.GROUP_NAME[r['group']]}",
                   [("Voices", "Female" if r["gender"] == "female" else "Male"), ("Style", r["style"])])

    saved = S.saved.get(pid, {})
    for crit, _, _ in QUESTIONS:  # prefill a revisited pair; widget state is dropped once a pair is left
        if f"{pid}|{crit}" not in S and crit in saved:
            S[f"{pid}|{crit}"] = saved[crit]
    if f"{pid}|note" not in S and saved.get("note"):
        S[f"{pid}|note"] = saved["note"]

    with st.form(f"form_{pid}", border=False):
        cols = st.columns(2)
        for col, letter, cid in ((cols[0], "A", a), (cols[1], "B", b)):
            with col.container(key=f"voice_{letter}"):
                C.voice_header(letter)
                st.audio(str(C.AUDIO / f"{cid}.mp3"), format="audio/mpeg")
        with st.container(key="judge"):
            st.markdown('<p class="judge-title">Which voice is better?</p>', unsafe_allow_html=True)
            for crit, question, help_ in QUESTIONS:
                st.radio(question, CHOICES, format_func=CHOICE_LABEL.get, index=None, horizontal=True,
                         key=f"{pid}|{crit}", help=help_)
            st.text_area("Why?", key=f"{pid}|note", height=90,
                         placeholder="What made the better voice better, or what went wrong in the other? "
                                     "Wrong tones, mispronounced names, robotic rhythm, glitches…")
        if S.get("pair_error"):
            st.error(S.pair_error)
        c1, c2 = st.columns([2.2, 1])
        c1.form_submit_button("Save and next", type="primary", on_click=submit, args=(pid, False), width="stretch")
        c2.form_submit_button("Skip pair", on_click=submit, args=(pid, True), width="stretch")
    C.store_notice(get_store())


def view_list() -> None:
    top_bar()
    st.markdown('<h2 class="round-title" style="margin-top:0.8rem">Your pairs</h2>', unsafe_allow_html=True)
    st.caption(f"{done_count()} of {len(S.queue)} pairs saved. Open any pair to listen again or change your answer.")
    nxt = next_open()
    if nxt:
        st.button("Continue with the next pair", type="primary", on_click=go, args=("pair", nxt))
    for g, label, _ in C.GROUPS:
        ids = [pid for pid in S.queue if C.BY_ID[all_pairs()[pid]["round"]]["group"] == g]
        if not ids:
            continue
        C.section(f"{label} · {'native' if S.langs.get(g) == 'native' else 'speaker'}")
        for pid in ids:
            r = C.BY_ID[all_pairs()[pid]["round"]]
            state = S.status.get(pid)
            c1, c2, c3 = st.columns([4, 1.2, 1.2], vertical_alignment="center")
            c1.markdown(f'<div class="round-row-name">Pair {S.queue.index(pid) + 1} · {C.esc(r["title"])}<small>'
                        f'{"Female" if r["gender"] == "female" else "Male"} voices</small></div>',
                        unsafe_allow_html=True)
            c2.markdown(C.pill(state, "Answered"), unsafe_allow_html=True)
            c3.button("Change" if state else "Open", key=f"open_{pid}", on_click=go, args=("pair", pid),
                      width="stretch")


def view_done() -> None:
    top_bar()
    answered = sum(1 for pid in S.queue if S.status.get(pid) == "rated")
    skipped = sum(1 for pid in S.queue if S.status.get(pid) == "skipped")
    C.hero("All done", "Thank you. Every pair is saved.",
           f"You answered {answered} pair{'s' if answered != 1 else ''}"
           f"{f' and skipped {skipped}' if skipped else ''}. You can go back and change any answer.",
           style="margin-top:1rem")
    c1, c2, _ = st.columns([1.4, 1.6, 2])
    c1.button("Review your answers", on_click=go, args=("list",), width="stretch")
    c2.button("Add another language", on_click=go, args=("intro",), width="stretch")


def main() -> None:
    C.page_setup(TITLE)
    init_state()
    try:
        get_store()
    except Exception as exc:
        st.error(f"The answer sheet can't be opened, so nothing would be saved. Tell the organiser. ({exc})")
        st.stop()
    if S.view != "intro" and not S.queue:
        S.view = "intro"
    {"intro": view_intro, "pair": view_pair, "list": view_list, "done": view_done}[S.view]()
    C.scroll_to_top()


main()
