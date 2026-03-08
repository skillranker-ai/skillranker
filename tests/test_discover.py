"""Tests for backend.discover — content hashing functions."""

from backend.discover import compute_content_hash, compute_near_hash


def test_compute_content_hash_deterministic():
    """Same content should always produce the same hash."""
    content = "name: test\ndescription: A skill"
    h1 = compute_content_hash(content)
    h2 = compute_content_hash(content)
    assert h1 == h2
    assert len(h1) == 16  # 16 hex chars


def test_compute_content_hash_different_content():
    """Different content should produce different hashes."""
    h1 = compute_content_hash("content A")
    h2 = compute_content_hash("content B")
    assert h1 != h2


def test_compute_content_hash_empty():
    """Empty string should still produce a valid hash."""
    h = compute_content_hash("")
    assert len(h) == 16
    assert all(c in "0123456789abcdef" for c in h)


def test_compute_near_hash_normalizes_whitespace():
    """Near-hash should treat whitespace variations as identical."""
    content1 = "name: test\n\n  description: A skill  "
    content2 = "name: test description: A skill"
    h1 = compute_near_hash(content1)
    h2 = compute_near_hash(content2)
    assert h1 == h2


def test_compute_near_hash_case_insensitive():
    """Near-hash should be case-insensitive."""
    h1 = compute_near_hash("Name: Test Skill")
    h2 = compute_near_hash("name: test skill")
    assert h1 == h2


def test_compute_near_hash_uses_first_500_chars():
    """Near-hash should only use first 500 chars."""
    prefix = "A" * 500
    content1 = prefix + "DIFFERENT_SUFFIX_1"
    content2 = prefix + "DIFFERENT_SUFFIX_2"
    h1 = compute_near_hash(content1)
    h2 = compute_near_hash(content2)
    assert h1 == h2  # same first 500 chars → same hash
