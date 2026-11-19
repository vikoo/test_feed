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
import time
from datetime import datetime, timedelta, timezone

import requests
from loguru import logger

from cron.utils import locales

LEAD = timedelta(minutes=15)
REMIND_TYPES = ("FP1", "PRACTICE", "FP2", "QNR1", "Sprint", "Race")
MAX_PER_PASS = 1  # reminded sessions are at least 40 minutes apart; 2 due at once means bad data
STATE_BRANCH = "motogp-state"
STATE_PATH = "session_reminders_sent.json"
CONTROL_PATH = "control.json"

# Fixed copy: one heading and one body per session and language, the same every weekend except the GP
# name (Purple Sector pattern: "{emoji} {GP}" heading, session line as body). Approved by Ankur once;
# change it only here. No slang, no facts that change between weekends, never a lead time.
TEMPLATES = {
    "en": {
        "FP1": ("🏍️ {gp} is here!", "FP1 is about to start 🔥👀"),
        "PRACTICE": ("⏱️ {gp}: Practice", "Top 10 go to Q2 🏁🔥"),
        "FP2": ("🔧 {gp}: FP2", "Last practice before Q1 🛠️👀"),
        "QNR1": ("🎯 {gp}: Qualifying", "Q1 and Q2 are about to start ⏱️🔥"),
        "Sprint": ("⚡ {gp}: Sprint", "12 points up for grabs 🏁🔥"),
        "Race": ("🏆 {gp}: Race day", "25 points on the line 🏁🔥"),
    },
    "it": {
        "FP1": ("🏍️ {gp}: si parte!", "Le FP1 stanno per iniziare 🔥👀"),
        "PRACTICE": ("⏱️ {gp}: Practice", "La top 10 va in Q2 🏁🔥"),
        "FP2": ("🔧 {gp}: FP2", "Ultime libere prima della Q1 🛠️👀"),
        "QNR1": ("🎯 {gp}: Qualifiche", "Q1 e Q2 stanno per iniziare ⏱️🔥"),
        "Sprint": ("⚡ {gp}: Sprint", "12 punti in palio 🏁🔥"),
        "Race": ("🏆 {gp}: giorno di gara", "25 punti in palio 🏁🔥"),
    },
    "es": {
        "FP1": ("🏍️ ¡Llega el {gp}!", "La FP1 empieza en breve 🔥👀"),
        "PRACTICE": ("⏱️ {gp}: Práctica", "El top 10 va a Q2 🏁🔥"),
        "FP2": ("🔧 {gp}: FP2", "Última práctica antes de la Q1 🛠️👀"),
        "QNR1": ("🎯 {gp}: Clasificación", "La Q1 y la Q2 empiezan en breve ⏱️🔥"),
        "Sprint": ("⚡ {gp}: Sprint", "12 puntos en juego 🏁🔥"),
        "Race": ("🏆 {gp}: día de carrera", "25 puntos en juego 🏁🔥"),
    },
    "pt": {
        "FP1": ("🏍️ Chegou o {gp}!", "O FP1 vai começar 🔥👀"),
        "PRACTICE": ("⏱️ {gp}: Treino", "O top 10 vai ao Q2 🏁🔥"),
        "FP2": ("🔧 {gp}: FP2", "Último treino antes do Q1 🛠️👀"),
        "QNR1": ("🎯 {gp}: Classificação", "O Q1 e o Q2 vão começar ⏱️🔥"),
        "Sprint": ("⚡ {gp}: Sprint", "12 pontos em jogo 🏁🔥"),
        "Race": ("🏆 {gp}: dia de corrida", "25 pontos em jogo 🏁🔥"),
    },
    "fr": {
        "FP1": ("🏍️ {gp} : c'est parti !", "Les FP1 commencent bientôt 🔥👀"),
        "PRACTICE": ("⏱️ {gp} : Practice", "Le top 10 file en Q2 🏁🔥"),
        "FP2": ("🔧 {gp} : FP2", "Dernière séance avant la Q1 🛠️👀"),
        "QNR1": ("🎯 {gp} : Qualifs", "La Q1 et la Q2 commencent bientôt ⏱️🔥"),
        "Sprint": ("⚡ {gp} : Sprint", "12 points en jeu 🏁🔥"),
        "Race": ("🏆 {gp} : jour de course", "25 points en jeu 🏁🔥"),
    },
    "de": {
        "FP1": ("🏍️ {gp}: Es geht los!", "FP1 beginnt gleich 🔥👀"),
        "PRACTICE": ("⏱️ {gp}: Practice", "Top 10 direkt in Q2 🏁🔥"),
        "FP2": ("🔧 {gp}: FP2", "Letztes Training vor Q1 🛠️👀"),
        "QNR1": ("🎯 {gp}: Qualifying", "Q1 und Q2 beginnen gleich ⏱️🔥"),
        "Sprint": ("⚡ {gp}: Sprint", "12 Punkte zu holen 🏁🔥"),
        "Race": ("🏆 {gp}: Renntag", "25 Punkte zu holen 🏁🔥"),
    },
    "ja": {
        "FP1": ("🏍️ {gp}開幕！", "まもなくFP1スタート 🔥👀"),
        "PRACTICE": ("⏱️ {gp}：プラクティス", "トップ10はQ2直行 🏁🔥"),
        "FP2": ("🔧 {gp}：FP2", "予選前の最後の走行 🛠️👀"),
        "QNR1": ("🎯 {gp}：予選", "まもなくQ1・Q2スタート ⏱️🔥"),
        "Sprint": ("⚡ {gp}：スプリント", "12ポイントをかけた戦い 🏁🔥"),
        "Race": ("🏆 {gp}：決勝", "25ポイントをかけた戦い 🏁🔥"),
    },
    "ko": {
        "FP1": ("🏍️ {gp} 개막!", "FP1 곧 시작 🔥👀"),
        "PRACTICE": ("⏱️ {gp}: 프랙티스", "톱10은 Q2 직행 🏁🔥"),
        "FP2": ("🔧 {gp}: FP2", "예선 전 마지막 주행 🛠️👀"),
        "QNR1": ("🎯 {gp}: 예선", "Q1·Q2 곧 시작 ⏱️🔥"),
        "Sprint": ("⚡ {gp}: 스프린트", "12점이 걸린 승부 🏁🔥"),
        "Race": ("🏆 {gp}: 결승", "25점이 걸린 승부 🏁🔥"),
    },
    "zh": {
        "FP1": ("🏍️ {gp}开幕！", "FP1即将开始 🔥👀"),
        "PRACTICE": ("⏱️ {gp}：练习赛", "前10名直通Q2 🏁🔥"),
        "FP2": ("🔧 {gp}：FP2", "排位赛前最后一节练习 🛠️👀"),
        "QNR1": ("🎯 {gp}：排位赛", "Q1和Q2即将开始 ⏱️🔥"),
        "Sprint": ("⚡ {gp}：冲刺赛", "争夺12个积分 🏁🔥"),
        "Race": ("🏆 {gp}：正赛日", "争夺25个积分 🏁🔥"),
    },
    "ru": {
        "FP1": ("🏍️ {gp} начинается!", "FP1 скоро стартует 🔥👀"),
        "PRACTICE": ("⏱️ {gp}: Практика", "Топ-10 сразу в Q2 🏁🔥"),
        "FP2": ("🔧 {gp}: FP2", "Последняя практика перед Q1 🛠️👀"),
        "QNR1": ("🎯 {gp}: Квалификация", "Q1 и Q2 скоро стартуют ⏱️🔥"),
        "Sprint": ("⚡ {gp}: Спринт", "На кону 12 очков 🏁🔥"),
        "Race": ("🏆 {gp}: День гонки", "На кону 25 очков 🏁🔥"),
    },
}

# Results push ("results are in"), sent by the uploader once a session's results are readable in Strapi.
# Same rules as TEMPLATES: fixed copy per session and language, the GP name the only variable, approved by
# Ankur once (direction approved 2026-11-19). No push after Q1: the Qualifying one (after Q2) covers both.
RESULT_TYPES = ("FP1", "PRACTICE", "FP2", "QNR2", "Sprint", "Race")
RESULT_TEMPLATES = {
    "en": {
        "FP1": ("📊 {gp}: FP1 results", "See who topped FP1 👀🔥"),
        "PRACTICE": ("📊 {gp}: Practice", "Results are in: who made Q2? 🏁👀"),
        "FP2": ("📊 {gp}: FP2 results", "See who topped FP2 👀🔥"),
        "QNR2": ("🏁 {gp}: Grid is set", "See who took pole 👀🔥"),
        "Sprint": ("⚡ {gp}: Sprint results", "See who won the Sprint 🏆🔥"),
        "Race": ("🏆 {gp}: Race results", "See who won the Race 🏆🔥"),
    },
    "it": {
        "FP1": ("📊 {gp}: risultati FP1", "Scopri il più veloce delle FP1 👀🔥"),
        "PRACTICE": ("📊 {gp}: Practice", "Risultati: chi va in Q2? 🏁👀"),
        "FP2": ("📊 {gp}: risultati FP2", "Scopri il più veloce delle FP2 👀🔥"),
        "QNR2": ("🏁 {gp}: griglia decisa", "Scopri chi ha la pole 👀🔥"),
        "Sprint": ("⚡ {gp}: Sprint", "Risultati: scopri chi ha vinto la Sprint 🏆🔥"),
        "Race": ("🏆 {gp}: risultati gara", "Scopri chi ha vinto la gara 🏆🔥"),
    },
    "es": {
        "FP1": ("📊 {gp}: resultados FP1", "Mira quién fue el más rápido en FP1 👀🔥"),
        "PRACTICE": ("📊 {gp}: Práctica", "Resultados: ¿quién va a Q2? 🏁👀"),
        "FP2": ("📊 {gp}: resultados FP2", "Mira quién fue el más rápido en FP2 👀🔥"),
        "QNR2": ("🏁 {gp}: parrilla lista", "Mira quién se llevó la pole 👀🔥"),
        "Sprint": ("⚡ {gp}: Sprint", "Resultados: mira quién ganó la Sprint 🏆🔥"),
        "Race": ("🏆 {gp}: resultado final", "Mira quién ganó la carrera 🏆🔥"),
    },
    "pt": {
        "FP1": ("📊 {gp}: resultado FP1", "Veja quem foi o mais rápido no FP1 👀🔥"),
        "PRACTICE": ("📊 {gp}: Treino", "Resultados: quem vai ao Q2? 🏁👀"),
        "FP2": ("📊 {gp}: resultado FP2", "Veja quem foi o mais rápido no FP2 👀🔥"),
        "QNR2": ("🏁 {gp}: grid definido", "Veja quem ficou com a pole 👀🔥"),
        "Sprint": ("⚡ {gp}: Sprint", "Resultado: veja quem venceu a Sprint 🏆🔥"),
        "Race": ("🏆 {gp}: resultado final", "Veja quem venceu a corrida 🏆🔥"),
    },
    "fr": {
        "FP1": ("📊 {gp} : résultats FP1", "Qui a dominé les FP1 ? 👀🔥"),
        "PRACTICE": ("📊 {gp} : Practice", "Résultats : qui file en Q2 ? 🏁👀"),
        "FP2": ("📊 {gp} : résultats FP2", "Qui a dominé les FP2 ? 👀🔥"),
        "QNR2": ("🏁 {gp} : grille connue", "Découvre qui a signé la pole 👀🔥"),
        "Sprint": ("⚡ {gp} : Sprint", "Résultats : découvre qui a gagné 🏆🔥"),
        "Race": ("🏆 {gp} : résultat final", "Découvre le vainqueur de la course 🏆🔥"),
    },
    "de": {
        "FP1": ("📊 {gp}: FP1-Ergebnis", "Wer war in FP1 vorne? 👀🔥"),
        "PRACTICE": ("📊 {gp}: Practice", "Ergebnis da: Wer ist direkt in Q2? 🏁👀"),
        "FP2": ("📊 {gp}: FP2-Ergebnis", "Wer war in FP2 vorne? 👀🔥"),
        "QNR2": ("🏁 {gp}: Grid steht", "Sieh, wer auf Pole steht 👀🔥"),
        "Sprint": ("⚡ {gp}: Sprint-Ergebnis", "Sieh, wer den Sprint gewonnen hat 🏆🔥"),
        "Race": ("🏆 {gp}: Rennergebnis", "Sieh, wer das Rennen gewonnen hat 🏆🔥"),
    },
    "ja": {
        "FP1": ("📊 {gp}：FP1結果", "FP1トップは誰？ 👀🔥"),
        "PRACTICE": ("📊 {gp}：プラクティス結果", "Q2直行は誰？ 🏁👀"),
        "FP2": ("📊 {gp}：FP2結果", "FP2トップは誰？ 👀🔥"),
        "QNR2": ("🏁 {gp}：グリッド確定", "ポールポジションは誰？ 👀🔥"),
        "Sprint": ("⚡ {gp}：スプリント結果", "スプリント優勝は誰？ 🏆🔥"),
        "Race": ("🏆 {gp}：決勝結果", "決勝の優勝は誰？ 🏆🔥"),
    },
    "ko": {
        "FP1": ("📊 {gp}: FP1 결과", "FP1 1위는 누구? 👀🔥"),
        "PRACTICE": ("📊 {gp}: 프랙티스 결과", "Q2 직행은 누구? 🏁👀"),
        "FP2": ("📊 {gp}: FP2 결과", "FP2 1위는 누구? 👀🔥"),
        "QNR2": ("🏁 {gp}: 그리드 확정", "폴 포지션은 누구? 👀🔥"),
        "Sprint": ("⚡ {gp}: 스프린트 결과", "스프린트 우승자는 누구? 🏆🔥"),
        "Race": ("🏆 {gp}: 결승 결과", "결승 우승자는 누구? 🏆🔥"),
    },
    "zh": {
        "FP1": ("📊 {gp}：FP1成绩", "看看谁是FP1最快 👀🔥"),
        "PRACTICE": ("📊 {gp}：练习赛成绩", "谁直通Q2？ 🏁👀"),
        "FP2": ("📊 {gp}：FP2成绩", "看看谁是FP2最快 👀🔥"),
        "QNR2": ("🏁 {gp}：发车顺序出炉", "看看谁拿下杆位 👀🔥"),
        "Sprint": ("⚡ {gp}：冲刺赛成绩", "看看谁赢下冲刺赛 🏆🔥"),
        "Race": ("🏆 {gp}：正赛成绩", "看看谁赢下正赛 🏆🔥"),
    },
    "ru": {
        "FP1": ("📊 {gp}: итоги FP1", "Кто был быстрее всех в FP1? 👀🔥"),
        "PRACTICE": ("📊 {gp}: Практика", "Итоги: кто сразу в Q2? 🏁👀"),
        "FP2": ("📊 {gp}: итоги FP2", "Кто был быстрее всех в FP2? 👀🔥"),
        "QNR2": ("🏁 {gp}: квалификация", "Узнай, кто взял поул 👀🔥"),
        "Sprint": ("⚡ {gp}: итоги спринта", "Узнай, кто выиграл спринт 🏆🔥"),
        "Race": ("🏆 {gp}: итоги гонки", "Узнай, кто выиграл гонку 🏆🔥"),
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


def build_result_messages(grand_prix: dict, race_type: str) -> dict:
    """{lang: (title, body)} for the results push of one session. Same checks as build_messages: a failing
    language is dropped, English failing raises (nothing is sent)."""
    gp = gp_display_name((grand_prix.get("attributes") or {}).get("name"))
    if not gp:
        raise ValueError(f"Grand Prix name missing for GP {grand_prix.get('id')}")
    if race_type not in RESULT_TYPES:
        raise ValueError(f"no results push for session type {race_type}")
    out = {}
    for lang in ["en", *sorted(locales)]:
        title, body = RESULT_TEMPLATES[lang][race_type]
        title, body = title.format(gp=gp), body.format(gp=gp)
        if not valid(title, body):
            if lang == "en":
                raise ValueError(f"en {race_type} results push fails the checks: {title!r} | {body!r}")
            logger.warning(f"{lang} {race_type} results push fails the checks and is not sent: {title!r} | {body!r}")
            continue
        out[lang] = (title, body)
    return out


# Official timetable (motogp.com): /v1/events/{siteEventId} -> broadcasts, date_start with the real UTC
# offset. The reminder follows it, not Strapi: at Qatar 2026 every Strapi time was 1 hour late.
OFFICIAL_TYPES = {"FP1": "FP1", "PR": "PRACTICE", "FP2": "FP2", "Q1": "QNR1", "Q2": "QNR2", "SPR": "Sprint", "RAC": "Race"}
MISMATCH = timedelta(minutes=5)
_official_cache = {}


def fetch_official_sessions(site_event_id: str) -> dict:
    """{session type: {"start": datetime, "status": "NOT-STARTED"/"FINISHED"/"CANCELLED"/...}}."""
    r = requests.get(f"https://api.motogp.pulselive.com/motogp/v1/events/{site_event_id}",
                     headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    r.raise_for_status()
    out = {}
    for b in r.json().get("broadcasts") or []:
        if (b.get("category") or {}).get("acronym") == "MGP" and b.get("type") == "SESSION" \
                and b.get("shortname") in OFFICIAL_TYPES and b.get("date_start"):
            out.setdefault(OFFICIAL_TYPES[b["shortname"]],
                           {"start": datetime.fromisoformat(b["date_start"]).astimezone(timezone.utc),
                            "status": str(b.get("status") or "").upper()})
    return out


def fetch_official_starts(site_event_id: str) -> dict:
    return {t: v["start"] for t, v in fetch_official_sessions(site_event_id).items()}


_status_cache = {}


def official_status(race, now: datetime, fetch=fetch_official_sessions, ttl=timedelta(minutes=5)) -> str:
    """Official session status ("CANCELLED" for a cancelled session), "" when unknown."""
    site_event_id = (_gp(race).get("attributes") or {}).get("siteEventId")
    if not site_event_id:
        return ""
    hit = _status_cache.get(site_event_id)
    if not hit or now - hit[0] >= ttl:
        try:
            hit = (now, fetch(site_event_id))
            _status_cache[site_event_id] = hit
        except Exception as e:
            logger.warning(f"official status unavailable for {site_event_id}: {type(e).__name__}: {e}")
            if not hit:
                return ""
    return (hit[1].get(race["attributes"]["type"]) or {}).get("status", "")


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


def refresh_official(site_event_id, now: datetime, fetch=fetch_official_sessions) -> bool:
    """Read the official timetable again, bypassing the caches (last check before a push).
    False when the feed is unreachable: the cached times and status are kept."""
    if not site_event_id:
        return False
    try:
        sessions = fetch(site_event_id)
    except Exception as e:
        logger.warning(f"official timetable re-check failed for {site_event_id}, using the last copy: {type(e).__name__}: {e}")
        return False
    _official_cache[site_event_id] = (now, {t: v["start"] for t, v in sessions.items()})
    _status_cache[site_event_id] = (now, sessions)
    return True


def strapi_start(race) -> datetime:
    return datetime.fromisoformat(race["attributes"]["startTime"].replace("Z", "+00:00"))


def effective_start(race, now: datetime, official=official_starts) -> datetime:
    """Official start when the timetable has the session, else the Strapi start."""
    site_event_id = (_gp(race).get("attributes") or {}).get("siteEventId")
    return official(site_event_id, now).get(race["attributes"]["type"]) or strapi_start(race)


def session_key(race) -> str:
    """One key per real session, whatever the Strapi row: a duplicated race row (or a duplicated Grand
    Prix with the same official event) must not send a second push."""
    gp = _gp(race)
    event = (gp.get("attributes") or {}).get("siteEventId") or f"gp{gp.get('id')}"
    return f"{event}:{race['attributes']['type']}"


def due(races, now: datetime, sent_ids, official=official_starts, status=official_status):
    """Sessions whose reminder is due now: official start within the lead time, not started, not yet sent
    (by race id or by session key), and not cancelled in the official timetable (Australia 2026 Race)."""
    out, keys = [], set()
    for r in races:
        start = effective_start(r, now, official)
        key = session_key(r)
        if wants_reminder(r) and timedelta(0) < start - now <= LEAD and str(r["id"]) not in sent_ids \
                and key not in sent_ids and key not in keys:
            if status(r, now) == "CANCELLED":
                logger.info(f"race {r['id']} {r['attributes']['type']} is cancelled in the official timetable: no reminder")
                continue
            keys.add(key)
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

    def mark(self, keys, when: datetime, attempts: int = 4, pause: float = 5.0):
        """Record a sent session under every key given (race id and session key)."""
        keys = [keys] if isinstance(keys, (str, int)) else list(keys)
        for k in keys:
            self.local[str(k)] = when.astimezone(timezone.utc).isoformat()
        self.sent = {**self.sent, **self.local}
        if not self.remote:
            return
        last = None
        for attempt in range(attempts):
            try:
                if attempt:
                    time.sleep(pause * attempt)
                    self.load()  # stale sha or a failed write: merge the remote file and retry
                self._ensure_branch()
                payload = {"message": f"MotoGP session reminder sent: {', '.join(map(str, keys))}", "branch": STATE_BRANCH,
                           "content": base64.b64encode(json.dumps(self.sent, indent=1, sort_keys=True).encode()).decode()}
                if self.sha:
                    payload["sha"] = self.sha
                r = requests.put(self._url(f"contents/{STATE_PATH}"), headers=self._h(), json=payload, timeout=30)
                r.raise_for_status()
                self.sha = r.json()["content"]["sha"]
                return
            except Exception as e:
                last = e
        raise last


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
    # Same-day differences only (time_sync fixes the ones more than 6 h away): keep the planned time
    # in Strapi, follow the official one for the push, log it once. Not a failure of the run.
    for m in time_mismatches(races, now, official):
        if m not in logged:
            logger.warning(m)
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
        raw = control.get("skip_race_ids") or []
        skip = {str(x).strip() for x in ([raw] if isinstance(raw, (str, int)) else raw)}
        todo = [r for r in todo if str(r["id"]) not in skip]
    if todo and official is official_starts:
        # Last check before a push: the latest official timetable. A session moved or cancelled at the last
        # moment is no longer due now; the runner wakes again at the new reminder time.
        for site_event_id in {(_gp(r).get("attributes") or {}).get("siteEventId") for r in todo}:
            refresh_official(site_event_id, now)
        before = {str(r["id"]): effective_start(r, now, official) for r in todo}
        todo = [r for r in due(races, now, set(store.sent) | set(store.local), official) if str(r["id"]) in before]
        for rid in set(before) - {str(r["id"]) for r in todo}:
            logger.warning(f"race {rid}: changed in the latest official timetable just before the push; "
                           f"not sent now (sent at the new time if it still runs)")
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
            store.mark([str(r["id"]), session_key(r)], now)
        except Exception as e:
            problems.append(f"{label}: sent but not recorded, a later run may resend: {type(e).__name__}: {e}")
    return problems
