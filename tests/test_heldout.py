"""The old 68-message file was written in the same pass as the rules that scored it.

It is not a fresh set. The test prints the current rules score and does not
treat a high number as evidence of generalization. data/eval_fresh.json is
the set that was hashed before this rules pass.
"""

from scripts.evaluate import load_heldout, score


def test_seen_eval_file_still_scores(capsys):
    report = score(load_heldout())
    with capsys.disabled():
        print(
            f"\nPreviously published set (not fresh): classification {report['classification']:.1%} "
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
    assert report["n"] >= 66
    assert 0 <= report["classification"] <= 1
