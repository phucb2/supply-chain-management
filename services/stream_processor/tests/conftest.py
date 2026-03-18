import pytest

from app.main import app as faust_app


@pytest.fixture
def app():
    return faust_app
