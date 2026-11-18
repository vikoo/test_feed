"""MotoGP session reminder pushes, sent by the weekend runner about 15 minutes before each session.

Same pattern as the Purple Sector backend session-reminder cron: pick sessions starting within the lead
time, skip the ones already reminded, send to the language topics, record the session as sent.

Rules (mz-ops push playbook): one push before FP1, Practice, FP2, Q1 (not Q2, it follows Q1 at once),
Sprint and Race; no Warm Up; nothing for a cancelled Grand Prix. Copy never says "in 15 min" because
devices show it late; heading 3 to 4 words with an emoji, body under 50 characters with 2 to 3 emojis.
Copy is fixed and hand-written per language (TEMPLATES), the same every weekend except the GP name,
so what goes out is known in advance. Every push still passes `valid` before it is sent.

Sends only when MOTOZ_SESSION_PUSH is "on" (GitHub repository variable). Otherwise every due push is
logged as "would send" and nothing leaves the runner.

Sent sessions are recorded in session_reminders_sent.json on the motogp-state branch (not main: the
weather workflow pushes to main without pulling, so commits there would break its pushes).
"""
import base64
import json
import os
from datetime import datetime, timedelta, timezone

import requests
from loguru import logger

from cron.utils import locales

LEAD = timedelta(minutes=15)
REMIND_TYPES = ("FP1", "PRACTICE", "FP2", "QNR1", "Sprint", "Race")
MAX_PER_PASS = 2  # sessions are at least 25 minutes apart; more than 2 due at once means bad data
STATE_BRANCH = "motogp-state"
STATE_PATH = "session_reminders_sent.json"
CONTROL_PATH = "control.json"

# Fixed copy: one heading and one body per session and language, the same every weekend except the GP
# name (Purple Sector pattern: "{emoji} {GP}" heading, session line as body). Approved by Ankur once;
# change it only here. No slang, no facts that change between weekends, never a lead time.
TEMPLATES = {
    "en": {
        "FP1": ("🏍️ {gp} is here!", "FP1 starts now 🔥👀"),
        "PRACTICE": ("⏱️ {gp}: Practice", "Top 10 go to Q2 🏁🔥"),
        "FP2": ("🔧 {gp}: FP2", "Last practice before Q1 🛠️👀"),
        "QNR1": ("🎯 {gp}: Qualifying", "Pole fight starts now ⏱️🔥"),
        "Sprint": ("⚡ {gp}: Sprint", "12 points up for grabs 🏁🔥"),
        "Race": ("🏆 {gp}: Race day", "25 points on the line 🏁🔥"),
    },
    "it": {
        "FP1": ("🏍️ {gp}: si parte!", "Le FP1 iniziano ora 🔥👀"),
        "PRACTICE": ("⏱️ {gp}: Prove", "La top 10 va in Q2 🏁🔥"),
        "FP2": ("🔧 {gp}: FP2", "Ultime libere prima della Q1 🛠️👀"),
        "QNR1": ("🎯 {gp}: Qualifiche", "Caccia alla pole al via ⏱️🔥"),
        "Sprint": ("⚡ {gp}: Sprint", "12 punti in palio 🏁🔥"),
        "Race": ("🏆 {gp}: giorno di gara", "25 punti in palio 🏁🔥"),
    },
    "es": {
        "FP1": ("🏍️ ¡Llega el {gp}!", "Arranca la FP1 🔥👀"),
        "PRACTICE": ("⏱️ {gp}: Práctica", "El top 10 va a Q2 🏁🔥"),
        "FP2": ("🔧 {gp}: FP2", "Última práctica antes de la Q1 🛠️👀"),
        "QNR1": ("🎯 {gp}: Clasificación", "Arranca la lucha por la pole ⏱️🔥"),
        "Sprint": ("⚡ {gp}: Sprint", "12 puntos en juego 🏁🔥"),
        "Race": ("🏆 {gp}: día de carrera", "25 puntos en juego 🏁🔥"),
    },
    "pt": {
        "FP1": ("🏍️ Chegou o {gp}!", "O FP1 começa agora 🔥👀"),
        "PRACTICE": ("⏱️ {gp}: Treino", "O top 10 vai ao Q2 🏁🔥"),
        "FP2": ("🔧 {gp}: FP2", "Último treino antes do Q1 🛠️👀"),
        "QNR1": ("🎯 {gp}: Classificação", "A briga pela pole começa ⏱️🔥"),
        "Sprint": ("⚡ {gp}: Sprint", "12 pontos em jogo 🏁🔥"),
        "Race": ("🏆 {gp}: dia de corrida", "25 pontos em jogo 🏁🔥"),
    },
    "fr": {
        "FP1": ("🏍️ {gp} : c'est parti !", "Les FP1 démarrent 🔥👀"),
        "PRACTICE": ("⏱️ {gp} : Practice", "Le top 10 file en Q2 🏁🔥"),
        "FP2": ("🔧 {gp} : FP2", "Dernière séance avant la Q1 🛠️👀"),
        "QNR1": ("🎯 {gp} : Qualifs", "La chasse à la pole commence ⏱️🔥"),
        "Sprint": ("⚡ {gp} : Sprint", "12 points en jeu 🏁🔥"),
        "Race": ("🏆 {gp} : jour de course", "25 points en jeu 🏁🔥"),
    },
    "de": {
        "FP1": ("🏍️ {gp}: Es geht los!", "FP1 beginnt jetzt 🔥👀"),
        "PRACTICE": ("⏱️ {gp}: Practice", "Top 10 direkt in Q2 🏁🔥"),
        "FP2": ("🔧 {gp}: FP2", "Letztes Training vor Q1 🛠️👀"),
        "QNR1": ("🎯 {gp}: Qualifying", "Der Kampf um die Pole beginnt ⏱️🔥"),
        "Sprint": ("⚡ {gp}: Sprint", "12 Punkte zu holen 🏁🔥"),
        "Race": ("🏆 {gp}: Renntag", "25 Punkte zu holen 🏁🔥"),
    },
    "ja": {
        "FP1": ("🏍️ {gp}開幕！", "FP1スタート 🔥👀"),
        "PRACTICE": ("⏱️ {gp}：プラクティス", "トップ10はQ2直行 🏁🔥"),
        "FP2": ("🔧 {gp}：FP2", "予選前の最後の走行 🛠️👀"),
        "QNR1": ("🎯 {gp}：予選", "ポール争いスタート ⏱️🔥"),
        "Sprint": ("⚡ {gp}：スプリント", "12ポイントをかけた戦い 🏁🔥"),
        "Race": ("🏆 {gp}：決勝", "25ポイントをかけた戦い 🏁🔥"),
    },
    "ko": {
        "FP1": ("🏍️ {gp} 개막!", "FP1 시작 🔥👀"),
        "PRACTICE": ("⏱️ {gp}: 프랙티스", "톱10은 Q2 직행 🏁🔥"),
        "FP2": ("🔧 {gp}: FP2", "예선 전 마지막 주행 🛠️👀"),
        "QNR1": ("🎯 {gp}: 예선", "폴 포지션 경쟁 시작 ⏱️🔥"),
        "Sprint": ("⚡ {gp}: 스프린트", "12점이 걸린 승부 🏁🔥"),
        "Race": ("🏆 {gp}: 결승", "25점이 걸린 승부 🏁🔥"),
    },
    "zh": {
        "FP1": ("🏍️ {gp}开幕！", "FP1开始了 🔥👀"),
        "PRACTICE": ("⏱️ {gp}：练习赛", "前10名直通Q2 🏁🔥"),
        "FP2": ("🔧 {gp}：FP2", "排位赛前最后一节练习 🛠️👀"),
        "QNR1": ("🎯 {gp}：排位赛", "杆位争夺战开始 ⏱️🔥"),
        "Sprint": ("⚡ {gp}：冲刺赛", "争夺12个积分 🏁🔥"),
        "Race": ("🏆 {gp}：正赛日", "争夺25个积分 🏁🔥"),
    },
    "ru": {
        "FP1": ("🏍️ {gp} начинается!", "FP1 стартует 🔥👀"),
        "PRACTICE": ("⏱️ {gp}: Практика", "Топ-10 сразу в Q2 🏁🔥"),
        "FP2": ("🔧 {gp}: FP2", "Последняя практика перед Q1 🛠️👀"),
        "QNR1": ("🎯 {gp}: Квалификация", "Борьба за поул начинается ⏱️🔥"),
        "Sprint": ("⚡ {gp}: Спринт", "На кону 12 очков 🏁🔥"),
        "Race": ("🏆 {gp}: День гонки", "На кону 25 очков 🏁🔥"),
    },
}

MAX_TITLE, MAX_BODY = 35, 50
_UPPER_WORDS = {"GP", "USA", "UK"}


def gp_display_name(name: str) -> str:
    """'PORTUGAL GP 26' -> 'Portugal GP', 'GERMANY  GP 26' -> 'Germany GP', 'USA GP 26' -> 'USA GP'."""
    words = (name or "").split()
    if words and words[-1].isdigit():
        words = words[:-1]
    return " ".join(w if w.upper() in _UPPER_WORDS else w.capitalize() for w in words)


def emoji_count(text: str) -> int:
    n = 0
    for ch in text:
        cp = ord(ch)
        if cp >= 0x1F000 or 0x2300 <= cp <= 0x23FF or 0x2600 <= cp <= 0x27BF:
            n += 1
    return n


def valid(title: str, body: str) -> bool:
    """Last check before a push leaves: lengths, emoji count, every placeholder filled, no lead time."""
    return (0 < len(title) <= MAX_TITLE and 0 < len(body) <= MAX_BODY
            and 1 <= emoji_count(title) <= 2 and 1 <= emoji_count(body) <= 3
            and "{" not in title + body and "}" not in title + body and "15" not in title + body)


def _gp(race):
    return ((race.get("attributes") or {}).get("grandPrix") or {}).get("data") or {}


def wants_reminder(race) -> bool:
    attrs = race.get("attributes") or {}
    gp_attrs = _gp(race).get("attributes") or {}
    return attrs.get("type") in REMIND_TYPES and gp_attrs.get("isCancelled") is not True


def build_messages(race) -> dict:
    """{lang: (title, body)} for every language topic. Raises if a line fails `valid`, so a broken push
    is never sent (the problem is reported and the job ends red)."""
    gp = gp_display_name((_gp(race).get("attributes") or {}).get("name"))
    if not gp:
        raise ValueError(f"Grand Prix name missing for race {race.get('id')}")
    rtype = race["attributes"]["type"]
    out = {}
    for lang in ["en", *sorted(locales)]:
        title, body = TEMPLATES[lang][rtype]
        title, body = title.format(gp=gp), body.format(gp=gp)
        if not valid(title, body):
            if lang == "en":
                raise ValueError(f"en {rtype} fails the checks: {title!r} | {body!r}")
            logger.warning(f"{lang} {rtype} fails the checks and is not sent: {title!r} | {body!r}")
            continue
        out[lang] = (title, body)
    return out


# Official timetable (motogp.com): /v1/events/{siteEventId} -> broadcasts, date_start with the real UTC
# offset. The reminder follows it, not Strapi: at Qatar 2026 every Strapi time was 1 hour late.
OFFICIAL_TYPES = {"FP1": "FP1", "PR": "PRACTICE", "FP2": "FP2", "Q1": "QNR1", "Q2": "QNR2", "SPR": "Sprint", "RAC": "Race"}
MISMATCH = timedelta(minutes=5)
_official_cache = {}


def fetch_official_starts(site_event_id: str) -> dict:
    r = requests.get(f"https://api.motogp.pulselive.com/motogp/v1/events/{site_event_id}",
                     headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    r.raise_for_status()
    out = {}
    for b in r.json().get("broadcasts") or []:
        if (b.get("category") or {}).get("acronym") == "MGP" and b.get("type") == "SESSION" \
                and b.get("shortname") in OFFICIAL_TYPES and b.get("date_start"):
            out.setdefault(OFFICIAL_TYPES[b["shortname"]], datetime.fromisoformat(b["date_start"]).astimezone(timezone.utc))
    return out


def official_starts(site_event_id, now: datetime, fetch=fetch_official_starts, ttl=timedelta(minutes=10)) -> dict:
    """{session type: official start}, cached for ttl; {} when unknown or the feed is down."""
    if not site_event_id:
        return {}
    hit = _official_cache.get(site_event_id)
    if hit and now - hit[0] < ttl:
        return hit[1]
    try:
        starts = fetch(site_event_id)
    except Exception as e:
        logger.warning(f"official timetable unavailable for {site_event_id}: {type(e).__name__}: {e}")
        return hit[1] if hit else {}
    _official_cache[site_event_id] = (now, starts)
    return starts


def strapi_start(race) -> datetime:
    return datetime.fromisoformat(race["attributes"]["startTime"].replace("Z", "+00:00"))


def effective_start(race, now: datetime, official=official_starts) -> datetime:
    """Official start when the timetable has the session, else the Strapi start."""
    site_event_id = (_gp(race).get("attributes") or {}).get("siteEventId")
    return official(site_event_id, now).get(race["attributes"]["type"]) or strapi_start(race)


def due(races, now: datetime, sent_ids, official=official_starts):
    """Sessions whose reminder is due now: official start within the lead time, not started, not yet sent."""
    out = []
    for r in races:
        start = effective_start(r, now, official)
        if wants_reminder(r) and timedelta(0) < start - now <= LEAD and str(r["id"]) not in sent_ids:
            out.append(r)
    return out


def time_mismatches(races, now: datetime, official=official_starts) -> list:
    """Sessions whose Strapi time (what the app shows) differs from the official timetable."""
    out = []
    for r in races:
        eff, mine = effective_start(r, now, official), strapi_start(r)
        if abs(eff - mine) >= MISMATCH:
            out.append(f"race {r['id']} {r['attributes']['type']}: app shows {mine:%a %H:%M} UTC, official "
                       f"{eff:%a %H:%M} UTC. Reminder follows the official time; fix the time in Strapi.")
    return out


class SentStore:
    """Record of reminded sessions on the motogp-state branch, through the GitHub contents API.
    Outside GitHub Actions (no token) it keeps the record in memory only.

    Sessions sent by this job are kept locally and never dropped, even if the remote write failed, so a
    failed write can no longer resend the push on the next pass.

    control.json on the same branch lets a person act on a running job without cancelling it:
    {"session_push": "off"} pauses every reminder, {"skip_race_ids": ["606"]} skips one session
    (for example one that was cancelled). It is read before every send."""

    def __init__(self, token=None, repo=None):
        self.token = token if token is not None else os.getenv("GITHUB_TOKEN")
        self.repo = repo or os.getenv("GITHUB_REPOSITORY")
        self.sent = {}
        self.local = {}
        self.sha = None
        self.remote = bool(self.token and self.repo)

    def _url(self, path):
        return f"https://api.github.com/repos/{self.repo}/{path}"

    def _h(self):
        return {"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json"}

    def _get_json(self, path):
        """(content dict, sha); ({}, None) when the file or branch does not exist yet."""
        r = requests.get(self._url(f"contents/{path}"), params={"ref": STATE_BRANCH}, headers=self._h(), timeout=30)
        if r.status_code == 404:
            return {}, None
        r.raise_for_status()
        body = r.json()
        return json.loads(base64.b64decode(body["content"]).decode() or "{}"), body["sha"]

    def load(self):
        if self.remote:
            remote, self.sha = self._get_json(STATE_PATH)
            self.sent = {**remote, **self.local}
        else:
            self.sent = {**self.sent, **self.local}
        return self.sent

    def control(self) -> dict:
        if not self.remote:
            return {}
        data, _ = self._get_json(CONTROL_PATH)
        return data if isinstance(data, dict) else {}

    def _ensure_branch(self):
        r = requests.get(self._url(f"git/ref/heads/{STATE_BRANCH}"), headers=self._h(), timeout=30)
        if r.status_code == 200:
            return
        main = requests.get(self._url("git/ref/heads/main"), headers=self._h(), timeout=30)
        main.raise_for_status()
        c = requests.post(self._url("git/refs"), headers=self._h(), timeout=30,
                          json={"ref": f"refs/heads/{STATE_BRANCH}", "sha": main.json()["object"]["sha"]})
        if c.status_code not in (201, 422):  # 422: created meanwhile
            c.raise_for_status()

    def mark(self, race_id: str, when: datetime):
        self.local[str(race_id)] = when.astimezone(timezone.utc).isoformat()
        self.sent = {**self.sent, **self.local}
        if not self.remote:
            return
        self._ensure_branch()
        for attempt in range(2):
            payload = {"message": f"MotoGP session reminder sent: race {race_id}", "branch": STATE_BRANCH,
                       "content": base64.b64encode(json.dumps(self.sent, indent=1, sort_keys=True).encode()).decode()}
            if self.sha:
                payload["sha"] = self.sha
            r = requests.put(self._url(f"contents/{STATE_PATH}"), headers=self._h(), json=payload, timeout=30)
            if r.status_code in (409, 422) and attempt == 0:  # stale sha: merge the remote file and retry once
                self.load()
                continue
            r.raise_for_status()
            self.sha = r.json()["content"]["sha"]
            return


def run_pass(now: datetime, fetch_races, store: SentStore, send, enabled: bool, logged=None,
             official=official_starts):
    """One reminder pass. Returns problems (strings). `send(messages)` delivers {lang: (title, body)}."""
    problems = []
    logged = logged if logged is not None else set()
    try:
        # A wide window: the official time may be hours away from the Strapi time.
        races = fetch_races(now - timedelta(hours=3), now + timedelta(hours=3))
    except Exception as e:
        return [f"reminder lookup failed: {type(e).__name__}: {e}"]
    for m in time_mismatches(races, now, official):
        if m not in logged:
            logger.error(m)
            problems.append(m)
            logged.add(m)
    todo = due(races, now, set(store.sent) | set(store.local), official)
    if todo and enabled:
        try:
            todo = due(races, now, set(store.load()), official)  # re-check against the shared record
            control = store.control()
        except Exception as e:
            # Without the record a resend could reach every user twice: skip this pass instead.
            return problems + [f"reminder record unavailable, nothing sent: {type(e).__name__}: {e}"]
        if str(control.get("session_push", "on")).strip().lower() == "off":
            if "paused" not in logged:
                logger.warning("session reminders paused by control.json on the motogp-state branch")
                logged.add("paused")
            return problems
        skip = {str(x) for x in control.get("skip_race_ids") or []}
        todo = [r for r in todo if str(r["id"]) not in skip]
    if len(todo) > MAX_PER_PASS:
        return problems + [f"{len(todo)} reminders due at once, nothing sent (check session times): {[r['id'] for r in todo]}"]

    for r in todo:
        label = f"race {r['id']} {r['attributes']['type']} {effective_start(r, now, official):%Y-%m-%d %H:%M} UTC"
        try:
            messages = build_messages(r)
        except Exception as e:
            problems.append(f"{label}: {e}")
            continue
        if not enabled:
            if r["id"] not in logged:
                logger.info(f"[reminder dry run] would send {label}: {messages['en']} (+{len(messages) - 1} languages)")
                logged.add(r["id"])
            continue
        try:
            send(messages)
            logger.info(f"reminder sent {label}: {messages['en']}")
        except Exception as e:
            problems.append(f"{label}: send failed: {type(e).__name__}: {e}")
            continue
        try:
            store.mark(r["id"], now)
        except Exception as e:
            problems.append(f"{label}: sent but not recorded, a later run may resend: {type(e).__name__}: {e}")
    return problems
