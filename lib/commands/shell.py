"""Shell - интерактивный режим Homer"""
DESCRIPTION = "Интерактивный REPL-режим (как artisan tinker)"


def execute(context):
    from lib.shell import HomerShell
    from lib.command_loader import CommandLoader
    loader = CommandLoader(context['root_dir'] / 'commands')
    shell = HomerShell(
        context=context, command_loader=loader,
        config=context['config'],
    )
    shell.interact()
    return 0