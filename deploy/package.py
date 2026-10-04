"""Create a source-only deployment archive with an explicit path allowlist."""
import hashlib
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parent.parent
FOLDERS = ('apps', 'config', 'data', 'deploy', 'static', 'templates', 'tests')
FILES = ('manage.py', 'Dockerfile', 'compose.production.yaml', 'compose.yaml', 'railway.json',
         'requirements.lock', 'requirements.txt', 'requirements-dev.txt', '.dockerignore',
         '.gitignore', '.env.example', 'README.md', 'ADMIN_GUIDE.md', 'PRODUCTION.md',
         'CONTENT_REVIEW.md', 'IMPLEMENTATION.md', 'QA.md', 'start.ps1')
EXTENSIONS = {'.py', '.json', '.html', '.css', '.js', '.svg', '.png', '.jpg', '.jpeg',
              '.webp', '.woff', '.woff2', '.ttf', '.md', '.sh'}


def main():
    target = ROOT.parent / 'output' / 'ATHAR_Production.zip'
    target.parent.mkdir(exist_ok=True)
    paths = [ROOT / name for name in FILES]
    for folder in FOLDERS:
        paths.extend(path for path in (ROOT / folder).rglob('*')
                     if path.is_file() and not path.is_symlink() and '__pycache__' not in path.parts
                     and (path.suffix.lower() in EXTENSIONS or path.name == 'Caddyfile'))
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(set(paths)):
            archive.write(path, 'athar/' + path.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(target) as archive:
        assert archive.testzip() is None
        names = archive.namelist()
        assert all(not name.endswith(('.sqlite3', '.env', '.log', '.pyc')) for name in names)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    target.with_suffix('.sha256').write_text(f'{digest}  {target.name}\n', encoding='ascii')
    print(f'{target.name}: {len(names)} files; SHA256 {digest}')


if __name__ == '__main__':
    main()
