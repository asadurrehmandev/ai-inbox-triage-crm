"""Floors are the rates measured on data/eval_unseen.json, not a promise of perfection."""

from scripts.evaluate import load_heldout, score

# Measured when the frozen file was scored. Raise these only after a new measurement.
CLASSIFICATION_FLOOR = 68 / 68
FIELDS_PRESENT_FLOOR = 127 / 127
FALSE_VALUE_CEILING = 0 / 77


def test_heldout_meets_the_measured_floor(capsys):
    report = score(load_heldout())
    with capsys.disabled():
        print(
            f"\nHeld-out classification {report['classification']:.1%} "
            f"({report['classified']}/{report['n']})"
        )
        print(
            f"Fields with a value {report['fields_present']:.1%} "
            f"({report['present_hit']}/{report['present_total']})"
        )
        print(
            f"False values {report['false_value']:.1%} "
            f"({report['false_hit']}/{report['false_total']})"
        )
        for line in report["misses"]:
            print(f"  {line}")
    assert report["n"] >= 66
    assert report["classification"] >= CLASSIFICATION_FLOOR
    assert report["fields_present"] >= FIELDS_PRESENT_FLOOR
    assert report["false_value"] <= FALSE_VALUE_CEILING
