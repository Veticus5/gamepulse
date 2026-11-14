import pytest

from gamepulse.web.events import classify


@pytest.mark.parametrize(
    "title, category",
    [
        ("Path of Exile: Covens of Umbra is Now Available!", "content_release"),
        ("Counter-Strike 2 Update", "patch"),
        ("Hotfix 1.2.3", "patch"),
        ("Path of Exile 1 3.30 Expansion Timeline", "content_release"),
        ("Two Weeks Until ExileCon 2026!", "announcement"),
        ("Fan Art Competition Winners", "community"),
        ("Path of Exile 1: Covens of Umbra Twitch Drops", "community"),
        ("Watch the Path of Exile 1 ExileCon Qualifier Tomorrow - Earn Twitch Drops", "community"),
        ("The Last of the Druids Sale - Get One Free Mystery Box When You Spend Points", "sale"),
        ("A letter from the team", "other"),
        (None, "other"),
    ],
)
def test_category_from_title(title, category):
    assert classify(title, official=True)[0] == category


def test_priority_order_and_external_news():
    assert classify("Now Available", True)[1] > classify("Small Update", True)[1] > classify("Fan Art", True)[1]
    assert classify("Now Available", False) == ("content_release", 0)


def test_steam_patchnotes_tag_wins_over_title():
    assert classify("Fan Art and fixes", True, ["patchnotes"])[0] == "patch"
