from unittest.mock import patch

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.sources import crawl

# Captured at import, before the network guard replaces httpx.Client in every test.
REAL_CLIENT = httpx.Client


@pytest.fixture
def session_factory():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture(autouse=True)
def forget_dead_urls():
    crawl._dead.clear()


@pytest.fixture(autouse=True)
def no_real_network():
    # Code under test swallows many errors on purpose, so an attempt is recorded and the test fails afterwards.
    attempts = []

    def refuse(*args, **kwargs):
        attempts.append(args)
        raise RuntimeError("tests must not reach the network")

    with patch("app.sources.fetch.httpx.Client", side_effect=refuse), patch("app.sources.fetch.socket.getaddrinfo", side_effect=refuse):
        yield
    assert not attempts, "a test tried to reach the network"


@pytest.fixture
def real_client():
    return REAL_CLIENT
