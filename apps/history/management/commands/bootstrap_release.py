"""Explicit first-release initialization, suitable for hosts without SSH."""
import io
import os
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from apps.history.models import Entity


class Command(BaseCommand):
    help = 'Initialize public content and one admin when ATHAR_INITIALIZE=true; never resets existing accounts.'

    def handle(self, *args, **options):
        if os.getenv('ATHAR_INITIALIZE') != 'true':
            raise CommandError('Release initialization is not enabled')
        User = get_user_model()
        username = os.getenv('ATHAR_INITIAL_ADMIN_USERNAME', 'athar-admin')
        password = os.getenv('ATHAR_INITIAL_ADMIN_PASSWORD', '')
        with transaction.atomic():
            admin_exists = User.objects.filter(is_superuser=True).exists()
            if not admin_exists:
                if User.objects.filter(username=username).exists():
                    raise CommandError('The initial admin username already belongs to an existing account')
                try:
                    validate_password(password, User(username=username))
                except ValidationError:
                    raise CommandError('A strong initial administrator password is required') from None
            if not Entity.objects.exists():
                call_command('bootstrap_public_content', stdout=io.StringIO())
            if not admin_exists:
                User.objects.create_superuser(username=username, password=password, role='ADMIN')
                self.stdout.write('Initial administrator created. Remove initialization variables after deployment.')
            else:
                self.stdout.write('Existing administrator preserved.')
        self.stdout.write('Release initialization complete.')
