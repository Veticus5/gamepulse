import httpx
import pytest

from gamepulse.config import Game
from gamepulse.steam import make_client


@pytest.fixture
def games():
    return [Game(730, "Counter-Strike 2"), Game(570, "Dota 2")]


@pytest.fixture
def client_for():
    def build(handler):
        return make_client(httpx.MockTransport(handler))

    return build
