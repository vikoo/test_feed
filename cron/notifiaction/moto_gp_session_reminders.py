"""MotoGP session reminder pushes, sent by the weekend runner about 15 minutes before each session.

Same pattern as the Purple Sector backend session-reminder cron: pick sessions starting within the lead
time, skip the ones already reminded, send to the language topics, record the session as sent.

Rules (mz-ops push playbook): one push before FP1, Practice, FP2, Q1 (not Q2, it follows Q1 at once),
Sprint and Race; no Warm Up; nothing for a cancelled Grand Prix. Copy never says "in 15 min" because
devices show it late; heading 3 to 4 words with an emoji, body under 50 characters with 2 to 3 emojis.
Each language has hand-written copy: machine translation turns the slang into nonsense.

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

COUNTRY_CODES = {
    "Argentina": "AR", "Australia": "AU", "Austria": "AT", "Brazil": "BR", "Czech Republic": "CZ",
    "Czechia": "CZ", "France": "FR", "Germany": "DE", "Great Britain": "GB", "United Kingdom": "GB",
    "Hungary": "HU", "India": "IN", "Indonesia": "ID", "Italy": "IT", "Japan": "JP", "Kazakhstan": "KZ",
    "Malaysia": "MY", "Netherlands": "NL", "Portugal": "PT", "Qatar": "QA", "San Marino": "SM",
    "Spain": "ES", "Thailand": "TH", "United States": "US", "USA": "US",
}

# {flag}, {city} and {country} are filled from the Strapi track. Country names stay in English, so only
# the English Race heading uses {country}.
TEMPLATES = {
    "en": {
        "FP1": ("{flag} {city} is back!", "FP1 starts now 🏍️ time to lock in 🔥"),
        "PRACTICE": ("⚡ Q2 on the line", "Practice is go 🏁 top 10 skip Q1, no cap 🔥"),
        "FP2": ("🔧 FP2 starts now!", "Last setup call before quali 🛠️ lock in 👀"),
        "QNR1": ("🎯 Pole hunt starts now!", "Q1 is go ⏱️ only 2 make it to Q2 😤🔥"),
        "Sprint": ("⚡ Sprint time!", "12 pts up for grabs 🏁"),
        "Race": ("🏆 {country} GP is go!", "Race day is here 🔥 let him cook 🏍️💨"),
    },
    "es": {
        "FP1": ("{flag} ¡Volvemos a {city}!", "Arranca la FP1 🏍️ a tope 🔥"),
        "PRACTICE": ("⚡ La Q2 en juego", "Arranca la Práctica 🏁 el top 10 va a Q2 🔥"),
        "FP2": ("🔧 ¡Arranca la FP2!", "Último ajuste antes de la clasi 🛠️ 👀"),
        "QNR1": ("🎯 ¡A por la pole!", "Arranca la Q1 ⏱️ solo 2 pasan a Q2 😤🔥"),
        "Sprint": ("⚡ ¡Hora del Sprint!", "12 puntos en juego 🏁"),
        "Race": ("🏆 ¡Día de carrera!", "Arranca el GP 🔥 que empiece el show 🏍️💨"),
    },
    "it": {
        "FP1": ("{flag} Si torna a {city}!", "Via alle FP1 🏍️ testa bassa e gas 🔥"),
        "PRACTICE": ("⚡ In palio la Q2", "Via alle Prove 🏁 la top 10 va in Q2 🔥"),
        "FP2": ("🔧 Via alle FP2!", "Ultimo setup prima delle qualifiche 🛠️ 👀"),
        "QNR1": ("🎯 Caccia alla pole!", "Via alla Q1 ⏱️ solo 2 passano in Q2 😤🔥"),
        "Sprint": ("⚡ È l'ora della Sprint!", "12 punti in palio 🏁"),
        "Race": ("🏆 È il giorno della gara!", "Si parte 🔥 tutti davanti alla TV 🏍️💨"),
    },
    "pt": {
        "FP1": ("{flag} De volta a {city}!", "O FP1 começa agora 🏍️ foco total 🔥"),
        "PRACTICE": ("⚡ Vaga no Q2 em jogo", "O Treino começa 🏁 top 10 vai ao Q2 🔥"),
        "FP2": ("🔧 O FP2 começa agora!", "Último ajuste antes da quali 🛠️ 👀"),
        "QNR1": ("🎯 Caça à pole!", "O Q1 começa ⏱️ só 2 passam ao Q2 😤🔥"),
        "Sprint": ("⚡ Hora da Sprint!", "12 pontos em jogo 🏁"),
        "Race": ("🏆 Dia de corrida!", "O GP começa agora 🔥 bora 🏍️💨"),
    },
    "fr": {
        "FP1": ("{flag} Retour à {city} !", "Les FP1 commencent 🏍️ focus total 🔥"),
        "PRACTICE": ("⚡ La Q2 en jeu", "La Practice démarre 🏁 le top 10 file en Q2 🔥"),
        "FP2": ("🔧 Les FP2 démarrent !", "Dernier réglage avant les qualifs 🛠️ 👀"),
        "QNR1": ("🎯 Chasse à la pole !", "La Q1 démarre ⏱️ seuls 2 passent en Q2 😤🔥"),
        "Sprint": ("⚡ L'heure du Sprint !", "12 points en jeu 🏁"),
        "Race": ("🏆 C'est jour de course !", "Le GP démarre 🔥 place au show 🏍️💨"),
    },
    "de": {
        "FP1": ("{flag} {city} ist zurück!", "FP1 startet jetzt 🏍️ volle Konzentration 🔥"),
        "PRACTICE": ("⚡ Es geht um Q2", "Practice läuft 🏁 Top 10 direkt in Q2 🔥"),
        "FP2": ("🔧 FP2 startet jetzt!", "Letztes Setup vor dem Quali 🛠️ 👀"),
        "QNR1": ("🎯 Jagd auf die Pole!", "Q1 läuft ⏱️ nur 2 kommen in Q2 😤🔥"),
        "Sprint": ("⚡ Sprint-Zeit!", "12 Punkte zu holen 🏁"),
        "Race": ("🏆 Renntag!", "Das Rennen startet 🔥 Vollgas 🏍️💨"),
    },
    "ja": {
        "FP1": ("{flag} {city}ラウンド開幕！", "FP1スタート 🏍️ 集中していこう 🔥"),
        "PRACTICE": ("⚡ Q2直行をかけて", "プラクティス開始 🏁 トップ10がQ2直行 🔥"),
        "FP2": ("🔧 FP2スタート！", "予選前の最終セットアップ 🛠️ 👀"),
        "QNR1": ("🎯 ポール争いスタート！", "Q1開始 ⏱️ Q2に進めるのは2人だけ 😤🔥"),
        "Sprint": ("⚡ スプリントの時間！", "12ポイントをかけた戦い 🏁"),
        "Race": ("🏆 決勝の日！", "レーススタート 🔥 見逃すな 🏍️💨"),
    },
    "ko": {
        "FP1": ("{flag} {city} 주말 시작!", "FP1 시작 🏍️ 집중 모드 🔥"),
        "PRACTICE": ("⚡ Q2 직행을 건 승부", "프랙티스 시작 🏁 톱10은 Q2 직행 🔥"),
        "FP2": ("🔧 FP2 시작!", "예선 전 마지막 세팅 🛠️ 👀"),
        "QNR1": ("🎯 폴 포지션 사냥 시작!", "Q1 시작 ⏱️ Q2 진출은 단 2명 😤🔥"),
        "Sprint": ("⚡ 스프린트 시간!", "12점이 걸린 승부 🏁"),
        "Race": ("🏆 결승의 날!", "레이스 시작 🔥 놓치지 마세요 🏍️💨"),
    },
    "zh": {
        "FP1": ("{flag} {city}周末开启！", "FP1开始了 🏍️ 全神贯注 🔥"),
        "PRACTICE": ("⚡ 争夺Q2直通席位", "练习赛开始 🏁 前10直通Q2 🔥"),
        "FP2": ("🔧 FP2开始了！", "排位赛前最后调校 🛠️ 👀"),
        "QNR1": ("🎯 杆位争夺战开始！", "Q1开始 ⏱️ 只有2人晋级Q2 😤🔥"),
        "Sprint": ("⚡ 冲刺赛时间！", "12个积分等你争夺 🏁"),
        "Race": ("🏆 正赛日！", "正赛开始 🔥 千万别错过 🏍️💨"),
    },
    "ru": {
        "FP1": ("{flag} Уикенд: {city}!", "FP1 стартует 🏍️ полная концентрация 🔥"),
        "PRACTICE": ("⚡ Битва за Q2", "Практика стартует 🏁 топ-10 сразу в Q2 🔥"),
        "FP2": ("🔧 FP2 стартует!", "Последняя настройка перед квалой 🛠️ 👀"),
        "QNR1": ("🎯 Охота за поул!", "Q1 стартует ⏱️ в Q2 пройдут только 2 😤🔥"),
        "Sprint": ("⚡ Время спринта!", "На кону 12 очков 🏁"),
        "Race": ("🏆 День гонки!", "Гонка стартует 🔥 не пропусти 🏍️💨"),
    },
}


def flag(country: str) -> str:
    code = COUNTRY_CODES.get((country or "").strip())
    return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in code) if code else "🏁"


def _gp(race):
    return ((race.get("attributes") or {}).get("grandPrix") or {}).get("data") or {}


def _track(race):
    return (((_gp(race).get("attributes") or {}).get("track") or {}).get("data") or {}).get("attributes") or {}


def wants_reminder(race) -> bool:
    attrs = race.get("attributes") or {}
    gp_attrs = _gp(race).get("attributes") or {}
    return attrs.get("type") in REMIND_TYPES and gp_attrs.get("isCancelled") is not True


def build_messages(race) -> dict:
    """{lang: (title, body)} for every language topic. Raises if the track data is missing."""
    t = _track(race)
    city, country = t.get("city"), t.get("country")
    if not city or not country:
        raise ValueError(f"track city or country missing for race {race.get('id')}")
    values = {"flag": flag(country), "city": city, "country": country}
    rtype = race["attributes"]["type"]
    out = {}
    for lang in ["en", *sorted(locales)]:
        title, body = TEMPLATES.get(lang, TEMPLATES["en"])[rtype]
        out[lang] = (title.format(**values), body.format(**values))
    return out


def due(races, now: datetime, sent_ids):
    """Sessions whose reminder is due now: start within the lead time, not started, not yet sent."""
    out = []
    for r in races:
        start = datetime.fromisoformat(r["attributes"]["startTime"].replace("Z", "+00:00"))
        if wants_reminder(r) and timedelta(0) < start - now <= LEAD and str(r["id"]) not in sent_ids:
            out.append(r)
    return out


class SentStore:
    """Record of reminded sessions on the motogp-state branch, through the GitHub contents API.
    Outside GitHub Actions (no token) it keeps the record in memory only."""

    def __init__(self, token=None, repo=None):
        self.token = token if token is not None else os.getenv("GITHUB_TOKEN")
        self.repo = repo or os.getenv("GITHUB_REPOSITORY")
        self.sent = {}
        self.sha = None
        self.remote = bool(self.token and self.repo)

    def _url(self, path):
        return f"https://api.github.com/repos/{self.repo}/{path}"

    def _h(self):
        return {"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json"}

    def load(self):
        if not self.remote:
            return self.sent
        r = requests.get(self._url(f"contents/{STATE_PATH}"), params={"ref": STATE_BRANCH}, headers=self._h(), timeout=30)
        if r.status_code == 404:
            self.sha = None
            self.sent = {}
            return self.sent
        r.raise_for_status()
        body = r.json()
        self.sha = body["sha"]
        self.sent = json.loads(base64.b64decode(body["content"]).decode() or "{}")
        return self.sent

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
        self.sent[str(race_id)] = when.astimezone(timezone.utc).isoformat()
        if not self.remote:
            return
        self._ensure_branch()
        payload = {"message": f"MotoGP session reminder sent: race {race_id}", "branch": STATE_BRANCH,
                   "content": base64.b64encode(json.dumps(self.sent, indent=1, sort_keys=True).encode()).decode()}
        if self.sha:
            payload["sha"] = self.sha
        r = requests.put(self._url(f"contents/{STATE_PATH}"), headers=self._h(), json=payload, timeout=30)
        r.raise_for_status()
        self.sha = r.json()["content"]["sha"]


def run_pass(now: datetime, fetch_races, store: SentStore, send, enabled: bool, logged=None):
    """One reminder pass. Returns problems (strings). `send(messages)` delivers {lang: (title, body)}."""
    problems = []
    logged = logged if logged is not None else set()
    try:
        races = fetch_races(now, now + LEAD)
    except Exception as e:
        return [f"reminder lookup failed: {type(e).__name__}: {e}"]
    try:
        sent_ids = set(store.load()) if enabled else set(store.sent)
    except Exception as e:
        # Without the record a resend could reach every user twice: skip this pass instead.
        return [f"reminder record unavailable, nothing sent: {type(e).__name__}: {e}"]

    todo = due(races, now, sent_ids)
    if len(todo) > MAX_PER_PASS:
        return [f"{len(todo)} reminders due at once, nothing sent (check session times): {[r['id'] for r in todo]}"]

    for r in todo:
        label = f"race {r['id']} {r['attributes']['type']} {r['attributes']['startTime']}"
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
