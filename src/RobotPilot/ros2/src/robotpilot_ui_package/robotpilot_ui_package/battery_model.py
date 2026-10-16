"""Deterministic battery value helpers shared by the monitor and its tests."""


def normalize_percent(value):
    try:
        percent = float(value)
    except (TypeError, ValueError):
        return None
    if percent != percent or percent in (float("inf"), float("-inf")):
        return None
    if not 0.0 <= percent <= 100.0:
        return None
    return percent


def advance_simulated_percent(percent, elapsed_seconds, charging, drain_rate, charge_rate):
    """Advance a controlled linear battery scenario using an injected time step."""
    current = normalize_percent(percent)
    if current is None:
        raise ValueError("percent must be between 0 and 100")
    elapsed = max(0.0, float(elapsed_seconds))
    rate = float(charge_rate if charging else drain_rate)
    if rate < 0:
        raise ValueError("battery rates must not be negative")
    delta = elapsed * rate * (1.0 if charging else -1.0)
    return min(100.0, max(0.0, current + delta))


def resolve_simulation_scenario(name, current_percent, initial_percent):
    """Return bounded scenario state for deterministic battery simulation."""
    scenarios = {
        "normal_discharge": (76.5, False, True, ""),
        "low_battery": (10.0, False, True, ""),
        "simulated_charging": (55.0, True, True, ""),
        "full": (100.0, True, True, ""),
        "communication_lost": (normalize_percent(current_percent), False, False, ""),
        "charging_fault": (55.0, False, True, "simulated_charging_failed"),
        "reset": (normalize_percent(initial_percent), False, True, ""),
    }
    if name not in scenarios:
        raise ValueError("unknown battery simulation scenario")
    return scenarios[name]


def update_low_battery_latch(active, percent, threshold, available, recovery_margin=3.0):
    """Apply a recovery margin so readings near the threshold do not chatter."""
    if not available:
        return None if active is None else bool(active)
    current = normalize_percent(percent)
    limit = normalize_percent(threshold)
    if current is None or limit is None:
        return None if active is None else bool(active)
    if active:
        return current < min(100.0, limit + max(0.0, float(recovery_margin)))
    return current <= limit
