import io
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command


@pytest.mark.django_db
def test_creates_superuser_from_env_when_none_exists():
    user_model = get_user_model()
    out = io.StringIO()

    with patch.dict(
        "os.environ",
        {
            "DJANGO_SUPERUSER_USERNAME": "admin",
            "DJANGO_SUPERUSER_PASSWORD": "adminpass123",
            "DJANGO_SUPERUSER_EMAIL": "admin@example.com",
        },
        clear=False,
    ):
        call_command("bootstrap_superuser", stdout=out)

    assert user_model.objects.filter(username="admin", is_superuser=True).exists()
    assert "Created bootstrap superuser: admin" in out.getvalue()


@pytest.mark.django_db
def test_skips_when_superuser_already_exists():
    user_model = get_user_model()
    user_model.objects.create_superuser(
        username="existing",
        password="pass12345",
        email="e@example.com",
    )

    out = io.StringIO()
    with patch.dict(
        "os.environ",
        {
            "DJANGO_SUPERUSER_USERNAME": "admin",
            "DJANGO_SUPERUSER_PASSWORD": "adminpass123",
        },
        clear=False,
    ):
        call_command("bootstrap_superuser", stdout=out)

    assert user_model.objects.filter(is_superuser=True).count() == 1
    assert user_model.objects.filter(username="existing", is_superuser=True).exists()
    assert "Superuser already exists. Skipping bootstrap." in out.getvalue()


@pytest.mark.django_db
def test_skips_when_env_is_missing():
    user_model = get_user_model()
    out = io.StringIO()

    with patch.dict(
        "os.environ",
        {
            "DJANGO_SUPERUSER_USERNAME": "",
            "DJANGO_SUPERUSER_PASSWORD": "",
            "DJANGO_SUPERUSER_EMAIL": "",
        },
        clear=False,
    ):
        call_command("bootstrap_superuser", stdout=out)

    assert user_model.objects.filter(is_superuser=True).count() == 0
    assert (
        "No superuser exists, but DJANGO_SUPERUSER_USERNAME/PASSWORD are not set."
        in out.getvalue()
    )
