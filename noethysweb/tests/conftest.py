import os

import pytest
from django.conf.global_settings import SESSION_COOKIE_NAME
from playwright.sync_api import Page

os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    """Configure browser context for all tests."""
    return {
        **browser_context_args,
        "ignore_https_errors": True,
        "locale": "fr-FR",
        "timezone_id": "Europe/Paris",
    }


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args):
    """Headless in CI (HEADLESS=1 env var), headed locally by default."""
    return {
        **browser_type_launch_args,
        "headless": os.environ.get("HEADLESS", "0") == "1",
    }


@pytest.fixture
def admin_user(db):
    """Staff user with full access. Used by all E2E tests that need an authenticated session."""
    from core.models import Utilisateur

    return Utilisateur.objects.create_superuser(
        username="admin",
        password="testpassword",
        email="admin@test.org",
        categorie="utilisateur",
    )


@pytest.fixture
def auto_login_user(db, client, live_server, page: Page):
    """Factory fixture: force-logs in a user and injects the session cookie into the Playwright page."""

    def make_auto_login(user):
        client.force_login(user)
        session_cookie = client.cookies[SESSION_COOKIE_NAME]

        page.context.add_cookies(
            [
                {
                    "name": SESSION_COOKIE_NAME,
                    "value": session_cookie.value,
                    "domain": live_server.url.split("//")[1].split(":")[0],
                    "path": "/",
                }
            ]
        )

        return page

    return make_auto_login
