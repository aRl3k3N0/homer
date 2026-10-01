"""
Top-level worker для ProcessPoolExecutor.
"""
import io
import sys
import time
import traceback
from pathlib import Path


def run_job_in_process(payload: dict) -> dict:
    started = time.time()
    root_dir = Path(payload['root_dir'])
    sys.path.insert(0, str(root_dir))

    exit_code = 0
    output = ''
    error = None
    buf = io.StringIO()

    try:
        from lib.config import Config
        from lib.logger import Logger
        from lib.arguments import ArgumentParser
        from lib.command_loader import CommandLoader
        from lib.queue import QueueStorage, Dispatcher

        config = Config(Path(payload['config_path']))
        logger = Logger(config, root_dir / 'logs')

        command = payload['command']
        args = payload['args'] or {}
        parts = [command]
        for k, v in args.items():
            if isinstance(v, bool):
                if v:
                    parts.append(f'--{k}')
            else:
                parts.append(f'--{k}={v}')

        parser = ArgumentParser()
        parser.parse(parts)

        loader = CommandLoader(root_dir / 'commands')
        commands = loader.load_commands()
        try:
            from lib.commands import BUILTIN_COMMANDS
            for name, info in BUILTIN_COMMANDS.items():
                commands.setdefault(name, info)
        except Exception:
            pass

        cmd_name = parser.command
        if cmd_name not in commands:
            raise RuntimeError(f"Команда '{cmd_name}' не найдена")

        queue_storage = QueueStorage(config)
        dispatcher = Dispatcher(
            queue_storage,
            config=config,
            triggered_by=payload.get('triggered_by') or 'process-worker',
        )
        dispatcher._parent_job_id = payload['job_id']

        def cancel_check():
            return queue_storage.is_cancel_requested(payload['job_id'])

        ctx = {
            'config': config,
            'logger': logger,
            'args': parser.options,
            'root_dir': root_dir,
            'command_name': cmd_name,
            'queue': dispatcher,
            'cancel_check': cancel_check,
        }

        import contextlib
        with contextlib.redirect_stdout(buf):
            result = commands[cmd_name]['execute'](ctx)

        exit_code = 0 if result in (None, 0, True) else int(result or 0)
    except Exception as e:
        error = f"{e}\n{traceback.format_exc()[:4000]}"
        exit_code = 1

    output = buf.getvalue()
    return {
        'exit_code': exit_code,
        'output': output,
        'error': error,
        'duration': time.time() - started,
    }