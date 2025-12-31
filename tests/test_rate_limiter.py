"""
Unit tests for RateLimiter.

The RateLimiter implements a token bucket algorithm to prevent
hitting API rate limits. These tests verify it works correctly.

To run these tests:
    pytest tests/test_rate_limiter.py
    pytest tests/test_rate_limiter.py -v
"""

import pytest
import time
import threading
from app import RateLimiter


# =============================================================================
# Basic Functionality Tests
# =============================================================================

@pytest.mark.unit
class TestRateLimiterBasics:
    """Tests for basic rate limiter functionality."""

    def test_initialization(self):
        """Test that rate limiter initializes correctly."""
        limiter = RateLimiter(rate=10, burst=20)

        assert limiter.rate == 10
        assert limiter.burst == 20
        assert limiter.tokens == 20  # Starts with burst capacity
        assert hasattr(limiter, 'lock')

    def test_acquire_with_available_tokens(self):
        """Test acquiring tokens when they're available."""
        limiter = RateLimiter(rate=10, burst=20)

        # Should successfully acquire a token
        assert limiter.acquire() is True

        # Should have one less token
        assert limiter.tokens == 19

    def test_acquire_multiple_tokens(self):
        """Test acquiring multiple tokens."""
        limiter = RateLimiter(rate=10, burst=10)

        # Acquire 5 tokens
        for i in range(5):
            assert limiter.acquire() is True

        # Should have approximately 5 tokens left (allow for timing variance)
        assert 4.9 <= limiter.tokens <= 5.1

    def test_acquire_without_tokens(self):
        """Test that acquire fails when no tokens available."""
        limiter = RateLimiter(rate=10, burst=1)

        # First acquire should succeed
        assert limiter.acquire() is True

        # Second acquire should fail (no tokens left)
        assert limiter.acquire() is False

    def test_acquire_until_exhausted(self):
        """Test acquiring all available tokens."""
        limiter = RateLimiter(rate=10, burst=5)

        # Acquire all 5 tokens
        for i in range(5):
            result = limiter.acquire()
            assert result is True, f"Failed to acquire token {i+1}"

        # Next acquire should fail
        assert limiter.acquire() is False


# =============================================================================
# Token Refill Tests
# =============================================================================

@pytest.mark.unit
class TestTokenRefill:
    """Tests for token replenishment over time."""

    def test_token_refill(self):
        """
        Test that tokens refill over time.

        With a rate of 10 tokens/second, after 0.2 seconds
        we should have approximately 2 tokens refilled.
        """
        limiter = RateLimiter(rate=10, burst=10)

        # Consume all tokens
        for _ in range(10):
            limiter.acquire()

        # No tokens available
        assert limiter.acquire() is False

        # Wait for tokens to refill (0.2 seconds = 2 tokens at 10/sec)
        time.sleep(0.2)

        # Should be able to acquire tokens now
        assert limiter.acquire() is True

    def test_token_refill_rate(self):
        """
        Test that tokens refill at the correct rate.

        At 5 tokens/second, after 1 second we should have
        approximately 5 tokens available.
        """
        limiter = RateLimiter(rate=5, burst=5)

        # Consume all tokens
        for _ in range(5):
            limiter.acquire()

        # Wait for 1 second
        time.sleep(1.0)

        # Should be able to acquire approximately 5 tokens
        acquired_count = 0
        for _ in range(6):  # Try to acquire 6
            if limiter.acquire():
                acquired_count += 1

        # Should have acquired around 5 tokens (allow some variance)
        assert 4 <= acquired_count <= 5, f"Expected 4-5 tokens, got {acquired_count}"

    def test_tokens_do_not_exceed_burst(self):
        """Test that tokens never exceed the burst limit."""
        limiter = RateLimiter(rate=10, burst=5)

        # Wait longer than needed to fill burst
        time.sleep(1.0)

        # Should have at most 5 tokens (burst limit)
        # Try to acquire more than burst
        acquired_count = 0
        for _ in range(10):
            if limiter.acquire():
                acquired_count += 1

        assert acquired_count == 5, f"Expected 5 tokens (burst limit), got {acquired_count}"


# =============================================================================
# Wait Method Tests
# =============================================================================

@pytest.mark.unit
class TestWaitMethod:
    """Tests for the wait() method."""

    def test_wait_when_tokens_available(self):
        """Test that wait returns immediately when tokens are available."""
        limiter = RateLimiter(rate=10, burst=10)

        start = time.time()
        limiter.wait()
        elapsed = time.time() - start

        # Should return almost immediately (< 0.1 seconds)
        assert elapsed < 0.1

    def test_wait_blocks_until_token_available(self):
        """Test that wait blocks until a token is available."""
        limiter = RateLimiter(rate=10, burst=1)

        # Use the one available token
        limiter.acquire()

        # Wait should block until token refills
        start = time.time()
        limiter.wait()
        elapsed = time.time() - start

        # Should have waited approximately 0.1 seconds (1/10)
        # Allow some variance for system timing
        assert 0.08 <= elapsed <= 0.2, f"Expected ~0.1s wait, got {elapsed}s"


# =============================================================================
# Thread Safety Tests
# =============================================================================

@pytest.mark.unit
class TestThreadSafety:
    """Tests for thread-safe token acquisition."""

    def test_concurrent_acquire(self):
        """Test that concurrent acquires are thread-safe."""
        limiter = RateLimiter(rate=100, burst=10)
        results = []

        def worker():
            """Worker thread that tries to acquire a token."""
            results.append(limiter.acquire())

        # Create 20 threads trying to acquire tokens
        threads = [threading.Thread(target=worker) for _ in range(20)]

        # Start all threads
        for t in threads:
            t.start()

        # Wait for all to complete
        for t in threads:
            t.join()

        # Exactly 10 should succeed (burst limit)
        successful_acquires = sum(results)
        assert successful_acquires == 10, \
            f"Expected exactly 10 successful acquires, got {successful_acquires}"

    def test_no_race_conditions(self):
        """Test that there are no race conditions in token counting."""
        limiter = RateLimiter(rate=100, burst=50)
        acquired_count = []

        def worker():
            """Worker that tries to acquire multiple tokens."""
            count = 0
            for _ in range(10):
                if limiter.acquire():
                    count += 1
            acquired_count.append(count)

        # Create 10 threads, each trying to acquire 10 tokens
        threads = [threading.Thread(target=worker) for _ in range(10)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Total acquired should be exactly 50 (burst limit)
        total_acquired = sum(acquired_count)
        assert total_acquired == 50, \
            f"Expected exactly 50 total acquires, got {total_acquired}"


# =============================================================================
# Edge Cases
# =============================================================================

@pytest.mark.unit
class TestEdgeCases:
    """Tests for edge cases and unusual scenarios."""

    def test_very_low_rate(self):
        """Test rate limiter with very low rate."""
        limiter = RateLimiter(rate=0.5, burst=1)  # 1 token every 2 seconds

        # Use the available token
        assert limiter.acquire() is True

        # Should not have another token yet
        assert limiter.acquire() is False

    def test_zero_burst(self):
        """Test rate limiter with zero burst (tokens capped at burst limit)."""
        limiter = RateLimiter(rate=10, burst=0)

        # No tokens initially
        assert limiter.tokens == 0

        # Should not be able to acquire immediately
        assert limiter.acquire() is False

        # Wait for token refill
        time.sleep(0.15)

        # With burst=0, tokens are capped at 0, so still can't acquire
        # This tests that burst limit is enforced correctly
        assert limiter.acquire() is False

    def test_very_high_rate(self):
        """Test rate limiter with very high rate."""
        limiter = RateLimiter(rate=1000, burst=100)

        # Should be able to acquire many tokens
        for _ in range(100):
            assert limiter.acquire() is True

        # After exhausting, should refill very quickly
        time.sleep(0.2)  # 0.2 seconds = 200 tokens at 1000/sec

        # Should have refilled to burst limit
        acquired = 0
        for _ in range(150):
            if limiter.acquire():
                acquired += 1

        assert acquired == 100, f"Expected 100 tokens after refill, got {acquired}"

    def test_fractional_tokens(self):
        """Test that fractional tokens are handled correctly."""
        limiter = RateLimiter(rate=3, burst=10)

        # Consume all tokens
        for _ in range(10):
            limiter.acquire()

        # Wait for 0.5 seconds (should give 1.5 tokens at rate=3)
        time.sleep(0.5)

        # Should be able to acquire 1 token (not 2, since 1.5 rounds to 1)
        assert limiter.acquire() is True
        # Second acquire might fail (fractional token)
        # This tests proper handling of fractional tokens
