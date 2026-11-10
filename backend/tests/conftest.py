import pytest

from app.sources import crawl


@pytest.fixture(autouse=True)
def forget_dead_urls():
    crawl._dead.clear()
