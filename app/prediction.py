from statistics import mean

def e1rm_epley(weight, reps):
    return weight * (1 + reps/30)

def suggest_next_load(sets, target_reps=(5,8), micro_step=2.5):
    if not sets:
        return None  # sin historial → pedir 1RM estimada o test de carga
    # usar últimos 3 sets
    last = sorted(sets, key=lambda s: s.created_at)[-3:]
    e1rms = [e1rm_epley(s.weight, s.reps) for s in last]
    base_e1rm = mean(e1rms)
    # objetivo: 70–80% e1RM para 5–8 reps aprox
    target_pct = 0.75
    proposed = base_e1rm * target_pct

    # ajuste por rendimiento último set
    s = last[-1]
    low, high = target_reps
    if s.reps > high and getattr(s, "rir", 2) >= 2:
        proposed *= 1.025    # +2.5%
    elif s.reps < low or getattr(s, "rir", 2) <= 0:
        proposed *= 0.975    # -2.5%

    # redondear a microcarga disponible
    def round_to_step(x, step):
        return round(x / step) * step
    return round_to_step(proposed, micro_step)