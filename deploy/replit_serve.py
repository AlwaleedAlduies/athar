"""Serve on Replit without running database migrations at build or startup."""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.replit_production')


def main():
    import django
    from django.core.management import call_command
    from waitress import serve

    django.setup()
    call_command('check', deploy=True, fail_level='WARNING')
    from config.wsgi import application
    serve(
        application,
        host='0.0.0.0',
        port=int(os.environ.get('PORT', '5000')),
        threads=8,
        trusted_proxy='*',
        trusted_proxy_headers={'x-forwarded-proto'},
        channel_timeout=650,
    )


if __name__ == '__main__':
    main()