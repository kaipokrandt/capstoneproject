import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Ensure a bootstrap superuser exists from DJANGO_SUPERUSER_* env vars"

    def handle(self, *args, **options):
        user_model = get_user_model()

        if user_model.objects.filter(is_superuser=True).exists():
            self.stdout.write("Superuser already exists. Skipping bootstrap.")
            return

        username = os.getenv("DJANGO_SUPERUSER_USERNAME", "").strip()
        password = os.getenv("DJANGO_SUPERUSER_PASSWORD", "")
        email = os.getenv("DJANGO_SUPERUSER_EMAIL", "").strip()

        if not username or not password:
            self.stdout.write(
                "No superuser exists, but DJANGO_SUPERUSER_USERNAME/PASSWORD are not set."
            )
            return

        user_model.objects.create_superuser(
            username=username,
            password=password,
            email=email or "",
        )
        self.stdout.write(f"Created bootstrap superuser: {username}")
