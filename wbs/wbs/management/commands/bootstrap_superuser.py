import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Ensure a bootstrap superuser exists from DJANGO_SUPERUSER_* env vars"

    def handle(self, *args, **options):
        user_model = get_user_model()

        username = os.getenv("DJANGO_SUPERUSER_USERNAME", "").strip()
        password = os.getenv("DJANGO_SUPERUSER_PASSWORD", "")
        email = os.getenv("DJANGO_SUPERUSER_EMAIL", "").strip()

        if not username or not password:
            self.stdout.write(
                "DJANGO_SUPERUSER_USERNAME/PASSWORD not set — skipping bootstrap."
            )
            return

        user, created = user_model.objects.get_or_create(
            username=username,
            defaults={"email": email or "", "is_staff": True, "is_superuser": True},
        )
        # Always sync the password from the env var so stale volumes never cause
        # login failures (e.g. after a password change in .env).
        user.set_password(password)
        if not user.is_superuser:
            user.is_superuser = True
        if not user.is_staff:
            user.is_staff = True
        if email:
            user.email = email
        user.save()

        if created:
            self.stdout.write(f"Created bootstrap superuser: {username}")
        else:
            self.stdout.write(f"Superuser '{username}' already exists — password synced from env.")
