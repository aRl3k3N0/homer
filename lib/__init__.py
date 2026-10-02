"""
Библиотеки и утилиты Homer
"""

from .arguments import ArgumentParser
from .command_loader import CommandLoader
from .config import Config
from .console import Color, Console, console
from .logger import Logger
from .mailer import Mailer, MailError

__version__ = "1.0.0"
__author__ = "Homer contributors"

__all__ = [
    'ArgumentParser',
    'Color',
    'CommandLoader',
    'Config',
    'Console',
    'Logger',
    'MailError',
    'Mailer',
    'console',
]
