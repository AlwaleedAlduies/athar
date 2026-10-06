"""One web process; migration/collectstatic failures stop the deployment."""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.production')


def prepare_railway_volume():
    """Railway mounts as root; grant the app ownership then drop privileges."""
    mount = os.environ.get('RAILWAY_VOLUME_MOUNT_PATH')
    if not mount or not hasattr(os, 'geteuid') or os.geteuid() != 0:
        return
    import pwd
    account = pwd.getpwnam('athar')
    media = Path(os.environ.get('MEDIA_ROOT', '/app/media')).resolve()
    if Path(mount).resolve() != media:
        raise RuntimeError('The Railway volume must be mounted at MEDIA_ROOT')
    media.mkdir(parents=True, exist_ok=True)
    os.chown(media, account.pw_uid, account.pw_gid)
    os.setgroups([])
    os.setgid(account.pw_gid)
    os.setuid(account.pw_uid)


def main():
    import django
    from django.core.management import call_command
    from waitress import serve

    port = int(os.environ.get('PORT', '8000'))
    if not 1 <= port <= 65535:
        raise ValueError('PORT must be between 1 and 65535')
    prepare_railway_volume()
    django.setup()
    production = os.environ['DJANGO_SETTINGS_MODULE'] == 'config.production'
    call_command('check', deploy=production, fail_level='WARNING' if production else 'ERROR')
    call_command('migrate', interactive=False)
    if os.getenv('ATHAR_INITIALIZE') == 'true':
        call_command('bootstrap_release')
    call_command('collectstatic', interactive=False, verbosity=0)
    from config.wsgi import application
    # Only the private proxy network can reach this port.
    serve(application, host='0.0.0.0', port=port, threads=8,
          trusted_proxy='*', trusted_proxy_headers={'x-forwarded-proto'},
          channel_timeout=650)


if __name__ == '__main__':
    main()
