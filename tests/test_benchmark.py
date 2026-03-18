"""Performance benchmarks for the resolver pipeline.

Run with: pytest tests/test_benchmark.py -v
Exclude from regular test runs with: pytest tests/ -v -m 'not benchmark'
"""

import pytest


@pytest.mark.benchmark
def test_alias_lookup_speed(benchmark, alias_dict):
    """Benchmark alias dictionary lookup speed.

    Target: < 0.01ms per lookup
    """
    result = benchmark(alias_dict.lookup, "ash")
    assert result is not None, "Benchmark should return a valid result"


@pytest.mark.benchmark
def test_fuzzy_match_speed(benchmark, fuzzy_matcher):
    """Benchmark fuzzy matching speed against full card database.

    Target: < 10ms against full 13k card database
    Note: This benchmark will be faster with pre-filtering (typically ~0.5-1ms)
    """
    result = benchmark(fuzzy_matcher.match, "Ash Blossom")
    assert len(result) > 0, "Benchmark should find matches"


@pytest.mark.benchmark
def test_phonetic_match_speed(benchmark, phonetic_matcher):
    """Benchmark phonetic matching speed.

    Target: < 5ms
    """
    result = benchmark(phonetic_matcher.match, "Nibirue")
    # Result may be empty or populated, just ensure it doesn't crash


@pytest.mark.benchmark
def test_full_pipeline_speed(benchmark, pipeline):
    """Benchmark full pipeline resolution for a typical commentary sentence.

    Target: < 20ms for a typical sentence with multiple candidates
    """
    text = "he activates Ash in response to the Branded Fusion and chains Imperm"
    result = benchmark(pipeline.resolve, text)
    # Result may vary, just ensure pipeline completes


@pytest.mark.benchmark
def test_pipeline_with_no_matches_speed(benchmark, pipeline):
    """Benchmark pipeline speed when no cards match.

    This tests the performance of the "miss" path through all tiers.
    """
    text = "and that's going to be game, what a fantastic finals"
    result = benchmark(pipeline.resolve, text)
    assert len(result) == 0, "Should not match any cards"


# Note: To see benchmark results, run:
#   pytest tests/test_benchmark.py -v --benchmark-only
#
# To compare against a baseline:
#   pytest tests/test_benchmark.py -v --benchmark-autosave
#   (then run again and compare)
