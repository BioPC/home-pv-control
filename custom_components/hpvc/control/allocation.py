"""Source-equivalent integer/milliwatt weighted delta and recovery water filling."""

import math
from .decisions import AllocationOutcome
from .models import AllocationResult, ControllerTarget
from ..inverter.generic_number import js_round


def _fill(amount, rooms, weights):
    assigned = [0] * len(rooms)
    active = [i for i, r in enumerate(rooms) if r > 0]
    while amount > 0 and active:
        total = sum(weights[i] for i in active)
        shares = {i: amount * weights[i] / total for i in active}
        saturated = [i for i in active if rooms[i] - assigned[i] <= shares[i]]
        if 0 < len(saturated) < len(active):
            for i in saturated:
                take = rooms[i] - assigned[i]
                assigned[i] += take
                amount -= take
            active = [i for i in active if i not in saturated]
            continue
        ranked = []
        taken = 0
        for i in active:
            take = min(rooms[i] - assigned[i], math.floor(shares[i]))
            assigned[i] += take
            taken += take
            ranked.append((i, shares[i] - math.floor(shares[i])))
        amount -= taken
        ranked.sort(key=lambda item: (-item[1], -weights[item[0]], item[0]))
        while amount > 0:
            progressed = False
            for i, _ in ranked:
                if amount > 0 and assigned[i] < rooms[i]:
                    assigned[i] += 1
                    amount -= 1
                    progressed = True
            if not progressed:
                break
        break
    return assigned, amount


def allocate(
    evaluation_id,
    requested_w,
    controllers,
    *,
    frozen_uids=(),
    rebalance=False,
    deadband_w=25,
):
    rows = tuple(
        c
        for c in controllers
        if c.participating and c.eligible and c.available and c.current_w is not None
    )
    reasons = [
        "unavailable_controller:" + c.uid
        for c in controllers
        if c.participating and not c.available
    ]
    reasons.extend(
        "ineligible_controller:" + c.uid
        for c in controllers
        if c.participating and not c.eligible
    )
    if requested_w is None:
        return AllocationOutcome(
            AllocationResult(evaluation_id, None, None), tuple(reasons)
        )
    if not rows:
        return AllocationOutcome(
            AllocationResult(evaluation_id, requested_w, 0.0, (), "capacity_shortfall"),
            tuple(reasons + ["capacity_shortfall"]),
        )
    scale = (
        1000
        if any(
            not float(v).is_integer()
            for c in rows
            for v in (c.current_w, c.minimum_w, c.full_w)
        )
        else 1
    )
    scaled = lambda v: int(js_round(v * scale))
    watts = lambda v: round(v / scale, 3)
    current = [scaled(c.current_w) for c in rows]
    minimum = [scaled(c.minimum_w) for c in rows]
    maximum = [scaled(c.full_w) for c in rows]
    weights = [c.full_w for c in rows]
    target = max(sum(minimum), min(sum(maximum), scaled(requested_w)))
    if requested_w < sum(minimum) / scale:
        reasons.append("hard_minimum")
    if requested_w > sum(maximum) / scale:
        reasons.append("capacity_shortfall")
    frozen = tuple(c.uid for c in rows if c.uid in frozen_uids)

    def outcome(values, applied=False, confirmed=False):
        if any(v == minimum[i] or v == maximum[i] for i, v in enumerate(values)):
            reasons.append("saturation")
        reasons.extend(
            "hard_minimum:" + c.uid
            for c, value, low in zip(rows, values, minimum)
            if value == low
        )
        reasons.extend(
            "saturation:" + c.uid
            for c, value, high in zip(rows, values, maximum)
            if value == high
        )
        allocated = watts(sum(values))
        shortfall = (
            ";".join(dict.fromkeys(reasons))
            if abs(allocated - requested_w) > 0.001
            else None
        )
        return AllocationOutcome(
            AllocationResult(
                evaluation_id,
                requested_w,
                allocated,
                tuple(ControllerTarget(c.uid, watts(v)) for c, v in zip(rows, values)),
                shortfall,
            ),
            tuple(dict.fromkeys(reasons)),
            frozen,
            applied,
            confirmed,
        )

    if rebalance and len(rows) > 1 and not frozen:
        delta, _ = _fill(
            target - sum(minimum),
            [hi - lo for hi, lo in zip(maximum, minimum)],
            weights,
        )
        absolute = [lo + d for lo, d in zip(minimum, delta)]
        confirmed = all(
            abs(cur - des)
            <= max(
                1,
                scaled(max(1, deadband_w)),
                math.ceil(scaled(c.step_w) / 2) if c.step_w > 0 else 1,
            )
            for c, cur, des in zip(rows, current, absolute)
        )
        if not confirmed:
            return outcome(absolute, True)
        # The source continues ordinary allocation after confirming an existing balance.
    else:
        confirmed = False
    direction = 1 if target > sum(current) else -1 if target < sum(current) else 0
    frozen_set = set(frozen) if direction > 0 else set()
    base = [
        cur if c.uid in frozen_set else max(lo, min(hi, cur))
        for c, cur, lo, hi in zip(rows, current, minimum, maximum)
    ]
    if frozen_set:
        target = min(
            target,
            sum(
                cur if c.uid in frozen_set else hi
                for c, cur, hi in zip(rows, current, maximum)
            ),
        )
        direction = 1 if target > sum(current) else -1 if target < sum(current) else 0
        reasons.extend("frozen_controller:" + uid for uid in frozen)
        if target < scaled(requested_w):
            reasons.append("capacity_shortfall")
    if (
        (direction > 0 and target < sum(base))
        or (direction < 0 and target > sum(base))
        or (direction == 0 and target != sum(base))
    ):
        return AllocationOutcome(
            AllocationResult(
                evaluation_id, requested_w, None, (), "direction_reversal_required"
            ),
            tuple(reasons + ["direction_reversal_required"]),
            frozen,
            blocked=True,
        )
    rooms = [
        0
        if c.uid in frozen_set
        else max(0, hi - b)
        if direction > 0
        else max(0, b - lo)
        if direction < 0
        else 0
        for c, b, lo, hi in zip(rows, base, minimum, maximum)
    ]
    changes, residual = _fill(abs(target - sum(base)), rooms, weights)
    if residual:
        return AllocationOutcome(
            AllocationResult(
                evaluation_id, requested_w, None, (), "allocation_residual"
            ),
            tuple(reasons + ["allocation_residual"]),
            frozen,
            blocked=True,
        )
    return outcome(
        [b + direction * d for b, d in zip(base, changes)], confirmed=confirmed
    )
