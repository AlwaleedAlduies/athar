import getpass
import os
from django.contrib.auth.password_validation import validate_password
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from apps.accounts.models import User, UserProfile

class Command(BaseCommand):
    help = 'Create a local admin using an interactive password or ATHAR_ADMIN_PASSWORD. No default password.'
    def add_arguments(self, parser):
        parser.add_argument('--username', default='admin')
        parser.add_argument('--email', default='')
    def handle(self, *args, **options):
        if User.objects.filter(username=options['username']).exists():
            raise CommandError('Username already exists; existing credentials were not changed.')
        password = os.getenv('ATHAR_ADMIN_PASSWORD') or getpass.getpass('Admin password: ')
        user = User(username=options['username'], email=options['email'], first_name='أمين المعرفة', role=User.Role.ADMIN, is_staff=True)
        validate_password(password, user)
        user.set_password(password)
        user.save()
        UserProfile.objects.create(user=user)
        self.stdout.write(self.style.SUCCESS('Administrator created.'))
