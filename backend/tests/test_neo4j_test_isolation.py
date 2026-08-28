"""
Phase 2B foundation repair - regression coverage for the Aug 26 incident
where ring-detection tests wrote real :Ring/MEMBER_OF_RING/Account/
Complaint data into the shared development Neo4j instance (47 orphaned
Ring nodes were found there afterward). Root cause: Postgres is reset per
test (in-memory SQLite) but Neo4j was not, and ring detection runs
whole-graph community detection, so no per-test cleanup query could ever
fully scope away what a single test run touched.

The actual fix is tests/conftest.py's NEO4J_URI default (points the whole
suite at the disposable `neo4j-test` docker-compose service instead of the
shared `neo4j` one) plus `_assert_test_neo4j_is_isolated`, which fails the
entire session loudly if that default is ever overridden back to the
shared instance. These tests exercise that guard function directly - no
Docker/Neo4j connectivity required, so they always run and always catch a
regression, even in an environment where the disposable instance itself
isn't up.
"""
import pytest

from app.core.config import get_settings
from tests.conftest import _assert_test_neo4j_is_isolated


@pytest.mark.parametrize(
    "uri",
    [
        "bolt://localhost:7687",
        "bolt://127.0.0.1:7687",
        "bolt://neo4j:7687",
    ],
)
def test_guard_rejects_the_shared_dev_neo4j_instance(uri):
    with pytest.raises(RuntimeError, match="shared development/production"):
        _assert_test_neo4j_is_isolated(uri)


@pytest.mark.parametrize(
    "uri",
    [
        "bolt://localhost:7688",  # the disposable neo4j-test service
        "bolt://neo4j-test:7687",  # same service, addressed by its compose hostname
        "bolt://localhost:7689",  # any other non-dev port
    ],
)
def test_guard_accepts_non_dev_instances(uri):
    _assert_test_neo4j_is_isolated(uri)  # must not raise


def test_this_test_process_is_actually_configured_against_the_disposable_instance():
    """Not just that the guard function *would* reject the shared instance
    in isolation - that the real, running test session's own resolved
    settings never point at it in the first place."""
    _assert_test_neo4j_is_isolated(get_settings().neo4j_uri)
    assert get_settings().neo4j_uri != "bolt://localhost:7687"
