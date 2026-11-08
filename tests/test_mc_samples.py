"""Monte Carlo samples (workflow/scripts/mc_samples.py)."""

import pandas as pd


def test_samples_shape_and_ranges(run_set):
    import mc_samples

    df = mc_samples.samples()
    assert df.shape == (32, len(mc_samples.RANGES))
    for k, (lo, hi) in mc_samples.RANGES.items():
        assert df[k].between(lo, hi).all(), k


def test_samples_reproducible(run_set):
    import mc_samples

    pd.testing.assert_frame_equal(mc_samples.samples(), mc_samples.samples())


def test_latin_hypercube_strata(run_set):
    """Each half of the sample (one seed) has one value in each of the 16 strata of every factor (up to the rounding
    of the values to four decimals, which can move a value across a stratum boundary)."""
    import mc_samples

    df = mc_samples.samples()
    for half in (df.iloc[:16], df.iloc[16:]):
        for k, (lo, hi) in mc_samples.RANGES.items():
            tol = 0.5e-4 / (hi - lo) * 16
            cands = [{min(max(int((v - lo) / (hi - lo) * 16 + e), 0), 15) for e in (-tol, tol)} for v in sorted(half[k])]
            taken = []
            for c in cands:  # values sorted: assign the lowest free stratum among the candidates
                free = sorted(c - set(taken))
                assert free, k
                taken.append(free[0])
            assert sorted(taken) == list(range(16)), k


def test_run_set_uses_samples(run_set):
    stored = pd.read_csv(run_set.RES / "mc_samples.csv", index_col=0)
    import mc_samples

    pd.testing.assert_frame_equal(stored, mc_samples.samples(), check_dtype=False)
