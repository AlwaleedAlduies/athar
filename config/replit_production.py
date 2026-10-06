"""Replit production settings; keep Railway's existing setup unchanged."""
import os

if not os.environ.get('SECRET_KEY') and os.environ.get('SESSION_SECRET'):
    os.environ['SECRET_KEY'] = os.environ['SESSION_SECRET']

from .production import *  # noqa: E402, F403

# Replit's startup probe requests / over the private HTTP connection. The edge
# terminates public HTTPS; all other application routes still enforce HTTPS.
SECURE_REDIRECT_EXEMPT = [r'^$', r'^healthz/$']