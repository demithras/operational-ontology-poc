import pytest
from r3_shared.clock import LogicalClock
from r3_shared.identity import IdentityProvider, TokenError


def test_valid_token_and_expiry():
    c = LogicalClock()
    idp = IdentityProvider("s3cret-s3cret")
    v = idp.verifier()
    t = idp.issue("alice", "svc", 5, c)
    assert v.verify(t, "svc", c) == "alice"
    c.advance(4)
    assert v.verify(t, "svc", c) == "alice"
    c.advance(1)
    with pytest.raises(TokenError, match="expired"):
        v.verify(t, "svc", c)


def test_forgery_and_audience():
    c = LogicalClock()
    idp = IdentityProvider("s3cret-s3cret")
    other = IdentityProvider("different-secret")
    v = idp.verifier()
    t = idp.issue("alice", "svc", 5, c)
    with pytest.raises(TokenError, match="audience"):
        v.verify(t, "other", c)
    with pytest.raises(TokenError, match="signature"):
        v.verify(other.issue("alice", "svc", 5, c), "svc", c)
    body, sig = t.split(".")
    forged = other.issue("root", "svc", 5, c).split(".")[0] + "." + sig
    with pytest.raises(TokenError):
        v.verify(forged, "svc", c)
    for bad in ("", "x", "a.b.c", None):
        with pytest.raises(TokenError):
            v.verify(bad, "svc", c)


def test_clock_rejects_negative():
    with pytest.raises(ValueError):
        LogicalClock().advance(-1)
