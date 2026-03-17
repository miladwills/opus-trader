import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from services.position_mode_helper import resolve_position_idx


def main() -> int:
    # Hedge mode checks
    assert resolve_position_idx("hedge", "Buy", False) == 1, "Hedge buy open should use idx=1"
    assert resolve_position_idx("hedge", "Sell", False) == 2, "Hedge sell open should use idx=2"
    assert resolve_position_idx("hedge", "Buy", True) == 2, "Hedge buy reduceOnly should close short leg idx=2"
    assert resolve_position_idx("hedge", "Sell", True) == 1, "Hedge sell reduceOnly should close long leg idx=1"

    # One-way mode should omit positionIdx
    assert resolve_position_idx("one_way", "Buy", False) is None, "One-way open should omit idx"
    assert resolve_position_idx("one_way", "Sell", True) is None, "One-way reduceOnly should omit idx"

    # Unknown mode should return None
    assert resolve_position_idx(None, "Buy", False) is None

    print("self_check_hedge_mode: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
