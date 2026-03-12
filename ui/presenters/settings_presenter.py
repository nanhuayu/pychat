"""Settings presenter - handles theme, proxy, and app settings."""
from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ui.main_window import MainWindow

logger = logging.getLogger(__name__)


class SettingsPresenter:
    """Handles application settings (theme, proxy, etc)."""

    def __init__(self, window: MainWindow):
        self._window = window

    def apply_theme(self) -> None:
        """Apply theme based on app settings."""
        try:
            project_root = os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            )
            theme = (self._window._app_settings.get('theme') or 'dark').lower()
            theme_file = 'light_theme.qss' if theme == 'light' else 'dark_theme.qss'
            theme_path = os.path.join(project_root, 'assets', 'styles', theme_file)
            base_theme_path = os.path.join(project_root, 'assets', 'styles', 'base.qss')

            parts: list[str] = []
            if os.path.exists(base_theme_path):
                with open(base_theme_path, 'r', encoding='utf-8') as f:
                    parts.append(f.read())
            if os.path.exists(theme_path):
                with open(theme_path, 'r', encoding='utf-8') as f:
                    parts.append(f.read())

            if parts:
                self._window.setStyleSheet("\n\n".join(parts))
        except Exception as e:
            logger.error("Error loading theme: %s", e)

    def apply_proxy(self) -> None:
        """Update environment variables for HTTP proxy."""
        proxy = self._window._app_settings.get('proxy_url', '').strip()
        if proxy:
            os.environ['HTTP_PROXY'] = proxy
            os.environ['HTTPS_PROXY'] = proxy
        else:
            os.environ.pop('HTTP_PROXY', None)
            os.environ.pop('HTTPS_PROXY', None)
