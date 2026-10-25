"""MotoGP championship tie-break key, per FIM Grand Prix World Championship Regulations 2026, Art. 1.28.7.

A tie in points is decided by the number of best results in the Grand Prix races
(count of 1st places, then 2nd, and so on). Sprint results are not taken into account.
If still tied, the date at which the highest place was achieved decides, latest result first.
"""

MAX_POSITION = 30
GRAND_PRIX_RACE_TYPE = "Race"


def _get_val(obj, path, default=None):
    for key in path:
        if not isinstance(obj, dict):
            return default
        obj = obj.get(key)
        if obj is None:
            return default
    return obj


def _classified_gp_results(race_results):
    """Yield (position, round) for each classified Grand Prix race finish."""
    for r in race_results:
        if _get_val(r, ["attributes", "race", "data", "attributes", "type"]) != GRAND_PRIX_RACE_TYPE:
            continue
        if _get_val(r, ["attributes", "dnf"]) is True:
            continue
        if _get_val(r, ["attributes", "classification", "data", "attributes", "type"]) is not None:
            continue
        pos = _get_val(r, ["attributes", "finalPos"])
        if pos is None:
            pos = _get_val(r, ["attributes", "position"])
        try:
            pos = int(pos)
        except (TypeError, ValueError):
            continue
        if not 1 <= pos <= MAX_POSITION:
            continue
        try:
            rnd = int(_get_val(r, ["attributes", "race", "data", "attributes", "grandPrix", "data", "attributes", "round"], 0))
        except (TypeError, ValueError):
            rnd = 0
        yield pos, rnd


def gp_tie_break_key(race_results):
    """Sort key, ascending order ranks better. Use after points: (-points, *gp_tie_break_key(results))."""
    finishes = list(_classified_gp_results(race_results))
    counts = [0] * (MAX_POSITION + 1)
    for pos, _ in finishes:
        counts[pos] += 1
    countback = tuple(-c for c in counts[1:])
    if finishes:
        best = min(pos for pos, _ in finishes)
        latest_best_round = max(rnd for pos, rnd in finishes if pos == best)
    else:
        latest_best_round = 0
    return countback, -latest_best_round
