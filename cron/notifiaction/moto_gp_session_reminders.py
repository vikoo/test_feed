"""MotoGP session reminder pushes, sent by the weekend runner about 15 minutes before each session.

Same pattern as the Purple Sector backend session-reminder cron: pick sessions starting within the lead
time, skip the ones already reminded, send to the language topics, record the session as sent.

Rules (mz-ops push playbook): one push before FP1, Practice, FP2, Q1 (not Q2, it follows Q1 at once),
Sprint and Race; no Warm Up; nothing for a cancelled Grand Prix. Copy never says "in 15 min" because
devices show it late; heading 3 to 4 words with an emoji, body under 50 characters with 2 to 3 emojis.
Each language has hand-written copy pools (machine translation turns the slang into nonsense); the
line rotates by round and every push passes `valid` before it is sent, so no one reviews pushes by hand.

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

# Copy pools. Each language has headings and bodies per session; heading and body rotate separately by
# round, so the pairing changes every weekend. {flag} {city} {country} come from the Strapi track,
# {leader} {gap} (Friday only) and {pole} (Sprint and Race only) from the official MotoGP API at send
# time. A line whose fact is missing, or that fails the checks in `valid`, is skipped for another one.
def _p(titles, bodies):
    return {"titles": titles, "bodies": bodies}


POOLS = {
    "en": {
        "FP1": _p(["{flag} {city} is back!", "{flag} {city} weekend is on!", "🏍️ Bikes are back out!",
                   "{flag} Welcome to {city}!", "🔥 New weekend unlocked", "{flag} {city}, let's go!"],
                  ["FP1 starts now 🏍️ time to lock in 🔥", "FP1 is go 🏁 first laps of the weekend 👀",
                   "Engines on 🔊 FP1 about to start 🏍️", "FP1 is go ⏱️ who sets the pace? 👀",
                   "{leader} leads by {gap} pts 👑 FP1 is go 🏍️", "First practice is go 🏍️ vibe check 🔥"]),
        "PRACTICE": _p(["⚡ Q2 on the line", "🎟️ Q2 ticket up for grabs", "⏱️ Top 10 or bust",
                        "🔥 Practice gets serious", "😤 No Q1 please", "⚡ Friday shootout"],
                       ["Practice is go 🏁 top 10 skip Q1, no cap 🔥", "Top 10 go straight to Q2 ⏱️ lock in 🔥",
                        "Practice is go 🏍️ time attack mode 😤", "{leader} leads by {gap} pts 👑 Practice is go 🏁",
                        "Practice is go 🏁 every tenth counts 👀", "Softs on 🔥 Practice about to start ⏱️"]),
        "FP2": _p(["🔧 FP2 starts now!", "🛠️ Setup o'clock", "🔧 Last tune-up", "👀 Race pace check",
                   "🔧 FP2 is go!", "🧪 Lab session time"],
                  ["Last setup call before quali 🛠️ lock in 👀", "FP2 is go 🔧 race pace reveal incoming 👀",
                   "Long runs or quick laps? 🤔 FP2 is go 🏍️", "Final tweaks before Q1 🛠️ FP2 is go 🔥",
                   "FP2 starts now 🏍️ tyre whisperers assemble 🔧", "FP2 is go ⏱️ who's got the pace? 👀"]),
        "QNR1": _p(["🎯 Pole hunt starts now!", "⏱️ Qualifying is go!", "🎯 Quali time!", "😤 Q1 survival mode",
                    "🔥 Grid battle is on", "🎯 One lap. Full send."],
                   ["Q1 is go ⏱️ only 2 make it to Q2 😤🔥", "2 Q2 spots, no second chances 😤 Q1 is go ⏱️",
                    "Quali is go 🎯 one lap to make it count 🔥", "Q1 then Q2 🏁 pole is up for grabs 🔥",
                    "Qualifying starts now ⏱️ send it 🏍️💨", "Fastest lap takes pole 🎯 quali is go 🔥"]),
        "Sprint": _p(["⚡ Sprint time!", "⚡ Saturday sprint is go!", "🏁 Half race, full chaos", "⚡ Sprint o'clock",
                      "🔥 Sprint is go!", "💨 Short race. No mercy."],
                     ["12 pts up for grabs 🏁", "12 pts up for grabs 🏁 no holding back 🔥",
                      "{pole} on pole 🎯 can anyone stop him? 🔥", "Half distance, zero chill 😤 Sprint is go 🏍️",
                      "Lights out soon ⚡ 12 pts on the line 🏁", "{pole} on pole 🎯 12 pts on the line 🏁"]),
        "Race": _p(["🏆 {country} GP is go!", "🏁 Race day!", "🏆 Sunday showdown", "🔥 It's race time!",
                    "{flag} {city} race day!", "🏁 25 pts on the line"],
                   ["Race day is here 🔥 let him cook 🏍️💨", "{pole} on pole 🎯 can he convert? 🏆",
                    "25 pts up for grabs 🏁 full send 🔥", "Lights out soon 🚦 this is the big one 🏆",
                    "{pole} on pole 🎯 can anyone stop him? 🔥", "Grand Prix is go 🏍️💨 don't blink 👀"]),
    },
    "it": {
        "FP1": _p(["{flag} Si torna a {city}!", "{flag} Weekend a {city}!", "🏍️ Si torna in pista!",
                   "{flag} Benvenuti a {city}!", "🔥 Nuovo weekend sbloccato", "{flag} {city}, ci siamo!"],
                  ["Via alle FP1 🏍️ testa bassa e gas 🔥", "FP1 al via 🏁 primi giri del weekend 👀",
                   "Motori accesi 🔊 FP1 in partenza 🏍️", "FP1 al via ⏱️ chi detta il ritmo? 👀",
                   "{leader} guida di {gap} punti 👑 FP1 al via 🏍️", "Prime libere al via 🏍️ si comincia 🔥"]),
        "PRACTICE": _p(["⚡ In palio la Q2", "🎟️ Biglietto per la Q2", "⏱️ Top 10 o niente",
                        "🔥 Le prove si fanno serie", "😤 Niente Q1, grazie", "⚡ Sfida del venerdì"],
                       ["Via alle Prove 🏁 la top 10 va in Q2 🔥", "La top 10 va dritta in Q2 ⏱️ concentrati 🔥",
                        "Prove al via 🏍️ modalità time attack 😤", "{leader} guida di {gap} punti 👑 Prove al via 🏁",
                        "Prove al via 🏁 ogni decimo conta 👀", "Gomme morbide 🔥 Prove in partenza ⏱️"]),
        "FP2": _p(["🔧 Via alle FP2!", "🛠️ Ora del setup", "🔧 Ultima messa a punto", "👀 Test del passo gara",
                   "🔧 FP2 al via!", "🧪 Si va in laboratorio"],
                  ["Ultimo setup prima delle qualifiche 🛠️ 👀", "FP2 al via 🔧 si scopre il passo gara 👀",
                   "Long run o giro secco? 🤔 FP2 al via 🏍️", "Ultimi ritocchi prima della Q1 🛠️ 🔥",
                   "FP2 al via 🏍️ parola alle gomme 🔧", "FP2 al via ⏱️ chi ha il passo? 👀"]),
        "QNR1": _p(["🎯 Caccia alla pole!", "⏱️ Qualifiche al via!", "🎯 Ora delle qualifiche!", "😤 Q1, si sopravvive",
                    "🔥 Battaglia per la griglia", "🎯 Un giro. Tutto o niente."],
                   ["Via alla Q1 ⏱️ solo 2 passano in Q2 😤🔥", "2 posti in Q2, zero seconde chance 😤 ⏱️",
                    "Qualifiche al via 🎯 un giro per stupire 🔥", "Q1 e poi Q2 🏁 la pole è in palio 🔥",
                    "Qualifiche al via ⏱️ tutto o niente 🏍️💨", "Il giro più veloce vale la pole 🎯 🔥"]),
        "Sprint": _p(["⚡ È l'ora della Sprint!", "⚡ Sprint del sabato!", "🏁 Mezza gara, caos totale", "⚡ Tempo di Sprint",
                      "🔥 Sprint al via!", "💨 Gara corta. Zero pietà."],
                     ["12 punti in palio 🏁", "12 punti in palio 🏁 nessuno si risparmia 🔥",
                      "{pole} in pole 🎯 chi lo ferma? 🔥", "Mezza distanza, zero calma 😤 Sprint al via 🏍️",
                      "Si parte a breve ⚡ 12 punti in palio 🏁", "{pole} in pole 🎯 12 punti in palio 🏁"]),
        "Race": _p(["🏆 È il giorno della gara!", "🏁 Giorno di gara!", "🏆 Resa dei conti domenicale", "🔥 È ora della gara!",
                    "{flag} Gara a {city}!", "🏁 25 punti in palio"],
                   ["Si parte 🔥 tutti davanti alla TV 🏍️💨", "{pole} in pole 🎯 riuscirà a vincere? 🏆",
                    "25 punti in palio 🏁 tutto o niente 🔥", "Semaforo a breve 🚦 è la gara che conta 🏆",
                    "{pole} in pole 🎯 chi lo ferma? 🔥", "Il GP è al via 🏍️💨 occhi aperti 👀"]),
    },
    "es": {
        "FP1": _p(["{flag} ¡Volvemos a {city}!", "{flag} ¡Finde en {city}!", "🏍️ ¡Vuelven las motos!",
                   "{flag} ¡Bienvenidos a {city}!", "🔥 Nuevo finde desbloqueado", "{flag} {city}, ¡vamos!"],
                  ["Arranca la FP1 🏍️ a tope 🔥", "FP1 en marcha 🏁 primeras vueltas del finde 👀",
                   "Motores encendidos 🔊 la FP1 ya llega 🏍️", "FP1 en marcha ⏱️ ¿quién marca el ritmo? 👀",
                   "{leader} lidera por {gap} pts 👑 arranca la FP1 🏍️", "Primeros libres en marcha 🏍️ a darlo todo 🔥"]),
        "PRACTICE": _p(["⚡ La Q2 en juego", "🎟️ Billete para la Q2", "⏱️ Top 10 o nada",
                        "🔥 La Práctica va en serio", "😤 Q1 no, gracias", "⚡ Duelo del viernes"],
                       ["Arranca la Práctica 🏁 el top 10 va a Q2 🔥", "El top 10 va directo a Q2 ⏱️ a full 🔥",
                        "Práctica en marcha 🏍️ modo time attack 😤", "{leader} lidera por {gap} pts 👑 Práctica ya 🏁",
                        "Práctica en marcha 🏁 cada décima cuenta 👀", "Blandos puestos 🔥 la Práctica ya llega ⏱️"]),
        "FP2": _p(["🔧 ¡Arranca la FP2!", "🛠️ Hora del setup", "🔧 Último ajuste", "👀 Ritmo de carrera",
                   "🔧 ¡FP2 en marcha!", "🧪 Hora de laboratorio"],
                  ["Último ajuste antes de la clasi 🛠️ 👀", "FP2 en marcha 🔧 se viene el ritmo real 👀",
                   "¿Tandas largas o vuelta rápida? 🤔 FP2 🏍️", "Últimos retoques antes de la Q1 🛠️ 🔥",
                   "Arranca la FP2 🏍️ que hablen los neumáticos 🔧", "FP2 en marcha ⏱️ ¿quién tiene ritmo? 👀"]),
        "QNR1": _p(["🎯 ¡A por la pole!", "⏱️ ¡Arranca la clasi!", "🎯 ¡Hora de clasificar!", "😤 Q1: a sobrevivir",
                    "🔥 Batalla por la parrilla", "🎯 Una vuelta. A muerte."],
                   ["Arranca la Q1 ⏱️ solo 2 pasan a Q2 😤🔥", "2 plazas para Q2, sin segundas 😤 ⏱️",
                    "Clasi en marcha 🎯 una vuelta para lucirse 🔥", "Q1 y luego Q2 🏁 la pole está en juego 🔥",
                    "Arranca la clasi ⏱️ todo o nada 🏍️💨", "La vuelta más rápida se lleva la pole 🎯 🔥"]),
        "Sprint": _p(["⚡ ¡Hora del Sprint!", "⚡ ¡Sprint del sábado!", "🏁 Media carrera, caos total", "⚡ Toca Sprint",
                      "🔥 ¡Sprint en marcha!", "💨 Carrera corta. Sin piedad."],
                     ["12 puntos en juego 🏁", "12 puntos en juego 🏁 nadie se guarda nada 🔥",
                      "{pole} en la pole 🎯 ¿quién lo para? 🔥", "Media distancia, cero calma 😤 Sprint ya 🏍️",
                      "Semáforo en breve ⚡ 12 puntos en juego 🏁", "{pole} en la pole 🎯 12 puntos en juego 🏁"]),
        "Race": _p(["🏆 ¡Día de carrera!", "🏁 ¡Hoy se corre!", "🏆 Duelo de domingo", "🔥 ¡Hora de la carrera!",
                    "{flag} ¡Carrera en {city}!", "🏁 25 puntos en juego"],
                   ["Arranca el GP 🔥 que empiece el show 🏍️💨", "{pole} en la pole 🎯 ¿podrá ganar? 🏆",
                    "25 puntos en juego 🏁 a por todas 🔥", "Semáforo en breve 🚦 esta es la buena 🏆",
                    "{pole} en la pole 🎯 ¿quién lo para? 🔥", "El GP está en marcha 🏍️💨 no parpadees 👀"]),
    },
    "pt": {
        "FP1": _p(["{flag} De volta a {city}!", "{flag} Fim de semana em {city}!", "🏍️ As motos voltaram!"],
                  ["O FP1 começa agora 🏍️ foco total 🔥", "FP1 valendo 🏁 primeiras voltas 👀",
                   "{leader} lidera por {gap} pts 👑 FP1 valendo 🏍️"]),
        "PRACTICE": _p(["⚡ Vaga no Q2 em jogo", "⏱️ Top 10 ou nada", "😤 Q1 não, obrigado"],
                       ["O Treino começa 🏁 top 10 vai ao Q2 🔥", "Treino valendo 🏁 cada décimo conta 👀",
                        "{leader} lidera por {gap} pts 👑 Treino valendo 🏁"]),
        "FP2": _p(["🔧 O FP2 começa agora!", "🛠️ Hora do acerto", "👀 Ritmo de corrida"],
                  ["Último ajuste antes da quali 🛠️ 👀", "FP2 valendo 🔧 vem aí o ritmo real 👀",
                   "Últimos ajustes antes do Q1 🛠️ 🔥"]),
        "QNR1": _p(["🎯 Caça à pole!", "⏱️ Quali valendo!", "😤 Q1: sobreviver"],
                   ["O Q1 começa ⏱️ só 2 passam ao Q2 😤🔥", "Q1 e depois Q2 🏁 a pole está em jogo 🔥",
                    "Quali valendo ⏱️ tudo ou nada 🏍️💨"]),
        "Sprint": _p(["⚡ Hora da Sprint!", "🔥 Sprint valendo!", "🏁 Meia corrida, caos total"],
                     ["12 pontos em jogo 🏁", "{pole} na pole 🎯 quem para ele? 🔥",
                      "Largada em breve ⚡ 12 pontos em jogo 🏁"]),
        "Race": _p(["🏆 Dia de corrida!", "🏁 Hoje tem corrida!", "{flag} Corrida em {city}!"],
                   ["O GP começa agora 🔥 bora 🏍️💨", "{pole} na pole 🎯 vai converter? 🏆",
                    "25 pontos em jogo 🏁 tudo ou nada 🔥"]),
    },
    "fr": {
        "FP1": _p(["{flag} Retour à {city} !", "{flag} Week-end à {city} !", "🏍️ Les motos sont de retour !"],
                  ["Les FP1 commencent 🏍️ focus total 🔥", "FP1 c'est parti 🏁 premiers tours 👀",
                   "{leader} mène de {gap} pts 👑 FP1 c'est parti 🏍️"]),
        "PRACTICE": _p(["⚡ La Q2 en jeu", "⏱️ Top 10 ou rien", "😤 Pas de Q1, merci"],
                       ["La Practice démarre 🏁 le top 10 file en Q2 🔥", "Practice lancée 🏁 chaque dixième compte 👀",
                        "{leader} mène de {gap} pts 👑 Practice lancée 🏁"]),
        "FP2": _p(["🔧 Les FP2 démarrent !", "🛠️ L'heure des réglages", "👀 Rythme de course"],
                  ["Dernier réglage avant les qualifs 🛠️ 👀", "FP2 c'est parti 🔧 le vrai rythme arrive 👀",
                   "Derniers réglages avant la Q1 🛠️ 🔥"]),
        "QNR1": _p(["🎯 Chasse à la pole !", "⏱️ Qualifs c'est parti !", "😤 Q1 : survivre"],
                   ["La Q1 démarre ⏱️ seuls 2 passent en Q2 😤🔥", "Q1 puis Q2 🏁 la pole est en jeu 🔥",
                    "Qualifs c'est parti ⏱️ tout ou rien 🏍️💨"]),
        "Sprint": _p(["⚡ L'heure du Sprint !", "🔥 Sprint c'est parti !", "🏁 Demi-course, chaos total"],
                     ["12 points en jeu 🏁", "{pole} en pole 🎯 qui va l'arrêter ? 🔥",
                      "Départ imminent ⚡ 12 points en jeu 🏁"]),
        "Race": _p(["🏆 C'est jour de course !", "🏁 Jour de course !", "{flag} Course à {city} !"],
                   ["Le GP démarre 🔥 place au show 🏍️💨", "{pole} en pole 🎯 va-t-il convertir ? 🏆",
                    "25 points en jeu 🏁 tout ou rien 🔥"]),
    },
    "de": {
        "FP1": _p(["{flag} {city} ist zurück!", "{flag} Wochenende in {city}!", "🏍️ Die Bikes sind zurück!"],
                  ["FP1 startet jetzt 🏍️ volle Konzentration 🔥", "FP1 läuft 🏁 erste Runden 👀",
                   "{leader} führt mit {gap} Pkt. 👑 FP1 läuft 🏍️"]),
        "PRACTICE": _p(["⚡ Es geht um Q2", "⏱️ Top 10 oder nichts", "😤 Bloß nicht Q1"],
                       ["Practice läuft 🏁 Top 10 direkt in Q2 🔥", "Practice läuft 🏁 jede Zehntel zählt 👀",
                        "{leader} führt mit {gap} Pkt. 👑 Practice läuft 🏁"]),
        "FP2": _p(["🔧 FP2 startet jetzt!", "🛠️ Zeit fürs Setup", "👀 Rennpace-Check"],
                  ["Letztes Setup vor dem Quali 🛠️ 👀", "FP2 läuft 🔧 jetzt zeigt sich die Pace 👀",
                   "Letzter Feinschliff vor Q1 🛠️ 🔥"]),
        "QNR1": _p(["🎯 Jagd auf die Pole!", "⏱️ Quali läuft!", "😤 Q1: überleben"],
                   ["Q1 läuft ⏱️ nur 2 kommen in Q2 😤🔥", "Erst Q1, dann Q2 🏁 die Pole ist offen 🔥",
                    "Quali läuft ⏱️ alles oder nichts 🏍️💨"]),
        "Sprint": _p(["⚡ Sprint-Zeit!", "🔥 Sprint läuft!", "🏁 Halbes Rennen, volles Chaos"],
                     ["12 Punkte zu holen 🏁", "{pole} auf Pole 🎯 wer stoppt ihn? 🔥",
                      "Gleich geht's los ⚡ 12 Punkte zu holen 🏁"]),
        "Race": _p(["🏆 Renntag!", "🏁 Heute wird gefahren!", "{flag} Rennen in {city}!"],
                   ["Das Rennen startet 🔥 Vollgas 🏍️💨", "{pole} auf Pole 🎯 holt er den Sieg? 🏆",
                    "25 Punkte zu holen 🏁 alles oder nichts 🔥"]),
    },
}

# Single line per session for the smaller markets (hand-written, checked like the pools).
_SINGLE = {
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
for _lang, _sessions in _SINGLE.items():
    POOLS[_lang] = {t: _p([title], [body]) for t, (title, body) in _sessions.items()}

FACT_SESSIONS = {"leader": ("FP1", "PRACTICE"), "gap": ("FP1", "PRACTICE"), "pole": ("Sprint", "Race")}
MAX_TITLE, MAX_BODY = 35, 50


def emoji_count(text: str) -> int:
    n, regional = 0, 0
    for ch in text:
        cp = ord(ch)
        if 0x1F1E6 <= cp <= 0x1F1FF:
            regional += 1
        elif cp >= 0x1F000 or 0x2300 <= cp <= 0x23FF or 0x2600 <= cp <= 0x27BF:
            n += 1
    return n + regional // 2


def valid(title: str, body: str) -> bool:
    """The automatic review every push passes before it is sent."""
    return (0 < len(title) <= MAX_TITLE and 0 < len(body) <= MAX_BODY
            and 1 <= emoji_count(title) <= 2 and 1 <= emoji_count(body) <= 3
            and "{" not in title + body and "}" not in title + body and "15" not in title + body)


def short_name(full_name: str) -> str:
    """'Marc Marquez' -> 'M. Marquez', 'Fabio Di Giannantonio' -> 'F. Di Giannantonio'."""
    parts = (full_name or "").split()
    return f"{parts[0][0]}. {' '.join(parts[1:])}" if len(parts) > 1 else (full_name or "")


def _fill(template: str, values: dict):
    try:
        return template.format(**values)
    except (KeyError, IndexError):
        return None


def pick(lang: str, rtype: str, values: dict, seed: int):
    """(title, body) for one language, or None when no line passes the checks.

    seed = season * 23 + round, unique per Grand Prix across seasons. The heading moves one step per
    round; the body also moves one step per round plus one extra step per full heading cycle, so every
    heading meets every body (36 pairs for a 6 x 6 pool) before any pair comes back, and two weekends
    in a row never share a heading or a body."""
    pool = POOLS.get(lang, POOLS["en"])[rtype]
    titles = [t for t in (_fill(x, values) for x in pool["titles"]) if t]
    bodies = [b for b in (_fill(x, values) for x in pool["bodies"]) if b]
    titles = [t for t in titles if valid(t, "ok 🏁")]
    bodies = [b for b in bodies if valid("ok 🏁", b)]
    if not titles or not bodies:
        return None
    ti, bi = rotation(seed, len(titles), len(bodies))
    return titles[ti], bodies[bi]


def rotation(seed: int, nt: int, nb: int):
    """(heading index, body index) for a seed. Heading: one step per weekend. Body: j + k*c, where j is
    the step inside the heading cycle and k the cycle number. c is coprime with nb (so every pair comes
    up) and chosen so the body also changes across a cycle boundary. If no such c exists (2 bodies and an
    even heading count), bodies just alternate: no back-to-back repeat beats full coverage."""
    j, k = seed % nt, seed // nt
    from math import gcd
    for c in range(1, max(nb, 2)):
        if gcd(c, nb) == 1 and (nb == 1 or (nt - 1 - c) % nb != 0):
            return j, (j + k * c) % nb
    return j, seed % nb


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


def build_messages(race, facts: dict = None) -> dict:
    """{lang: (title, body)} for every language topic. Facts are only used by the sessions they belong to
    (no standings on Sunday: they would give away the Sprint result). Raises if English has no line."""
    t = _track(race)
    city, country = t.get("city"), t.get("country")
    if not city or not country:
        raise ValueError(f"track city or country missing for race {race.get('id')}")
    rtype = race["attributes"]["type"]
    values = {"flag": flag(country), "city": city, "country": country}
    for key, value in (facts or {}).items():
        if value not in (None, "") and rtype in FACT_SESSIONS.get(key, ()):
            values[key] = value
    gp_attrs = _gp(race).get("attributes") or {}
    try:
        round_no = int(gp_attrs.get("round") or 0)
        year = int((((gp_attrs.get("season") or {}).get("data") or {}).get("attributes") or {}).get("year") or 0)
    except ValueError:
        round_no, year = 0, 0
    seed = year * 23 + round_no
    out = {}
    for lang in ["en", *sorted(locales)]:
        chosen = pick(lang, rtype, values, seed)
        if chosen:
            out[lang] = chosen
    if "en" not in out:
        raise ValueError(f"no English line passes the checks for race {race.get('id')} {rtype}")
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


def run_pass(now: datetime, fetch_races, store: SentStore, send, enabled: bool, logged=None, facts_for=None):
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
        facts = {}
        if facts_for:
            try:
                facts = facts_for(r) or {}
            except Exception as e:  # a missing fact never blocks the push: fact-free lines are used
                logger.warning(f"{label}: facts unavailable: {type(e).__name__}: {e}")
        try:
            messages = build_messages(r, facts)
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
