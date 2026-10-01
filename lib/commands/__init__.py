"""
Встроенные команды Homer.
"""
from . import shell
from . import make_command
from . import mail_check
from . import schedule
from . import queue
from . import notify
from . import webui
from . import schedule_async
from . import notify_plugins
from . import trace
from . import trace_watch
from . import history
from . import logs
from . import plugin
from . import make_migration
from . import make_plugin
from . import scaffold_upgrade


BUILTIN_COMMANDS = {
    'shell': {
        'execute': shell.execute,
        'description': shell.DESCRIPTION,
        'source': 'builtin',
    },
    'make:command': {
        'execute': make_command.execute,
        'description': make_command.DESCRIPTION,
        'source': 'builtin',
    },
    'mail:check': {
        'execute': mail_check.execute,
        'description': mail_check.DESCRIPTION,
        'source': 'builtin',
    },
    'schedule:add': {
        'execute': schedule.add,
        'description': schedule.DESCRIPTIONS['add'],
        'source': 'builtin',
    },
    'schedule:list': {
        'execute': schedule.list_tasks,
        'description': schedule.DESCRIPTIONS['list'],
        'source': 'builtin',
    },
    'schedule:remove': {
        'execute': schedule.remove,
        'description': schedule.DESCRIPTIONS['remove'],
        'source': 'builtin',
    },
    'schedule:enable': {
        'execute': schedule.enable,
        'description': schedule.DESCRIPTIONS['enable'],
        'source': 'builtin',
    },
    'schedule:disable': {
        'execute': schedule.disable,
        'description': schedule.DESCRIPTIONS['disable'],
        'source': 'builtin',
    },
    'schedule:run': {
        'execute': schedule.run_loop,
        'description': schedule.DESCRIPTIONS['run'],
        'source': 'builtin',
    },
    'schedule:tick': {
        'execute': schedule.tick,
        'description': schedule.DESCRIPTIONS['tick'],
        'source': 'builtin',
    },
    'queue:push': {
        'execute': queue.push,
        'description': queue.DESCRIPTIONS['push'],
        'source': 'builtin',
    },
    'queue:list': {
        'execute': queue.list_tasks,
        'description': queue.DESCRIPTIONS['list'],
        'source': 'builtin',
    },
    'queue:status': {
        'execute': queue.status,
        'description': queue.DESCRIPTIONS['status'],
        'source': 'builtin',
    },
    'queue:cancel': {
        'execute': queue.cancel,
        'description': queue.DESCRIPTIONS['cancel'],
        'source': 'builtin',
    },
    'queue:retry': {
        'execute': queue.retry,
        'description': queue.DESCRIPTIONS['retry'],
        'source': 'builtin',
    },
    'queue:purge': {
        'execute': queue.purge,
        'description': queue.DESCRIPTIONS['purge'],
        'source': 'builtin',
    },
    'queue:work': {
        'execute': queue.work,
        'description': queue.DESCRIPTIONS['work'],
        'source': 'builtin',
    },
    'notify:test': {
        'execute': notify.test,
        'description': notify.DESCRIPTION,
        'source': 'builtin',
    },
    '_run-job': {
        'execute': queue.run_job_subprocess_entry,
        'description': 'Внутренняя команда для subprocess-режима',
        'source': 'builtin',
    },
    'webui': {
        'execute': webui.execute,
        'description': webui.DESCRIPTION,
        'source': 'builtin',
    },
    'schedule-async': {
        'execute': schedule_async.execute,
        'description': schedule_async.DESCRIPTION,
        'source': 'builtin',
    },
    'notify:plugins': {
        'execute': notify_plugins.execute,
        'description': notify_plugins.DESCRIPTION,
        'source': 'builtin',
    },
    'trace:job': {
        'execute': trace.execute,
        'description': trace.DESCRIPTION,
        'source': 'builtin',
    },
    'trace:watch': {
        'execute': trace_watch.execute,
        'description': trace_watch.DESCRIPTION,
        'source': 'builtin',
    },
    'history': {
        'execute': history.execute,
        'description': history.DESCRIPTION,
        'source': 'builtin',
    },
    'logs': {
        'execute': logs.execute,
        'description': logs.DESCRIPTION,
        'source': 'builtin',
    },
'plugin:list':       {'execute': plugin.list_plugins,
                          'description': plugin.DESCRIPTIONS['list'],
                          'source': 'builtin'},
    'plugin:info':       {'execute': plugin.info,
                          'description': plugin.DESCRIPTIONS['info'],
                          'source': 'builtin'},
    'plugin:migrate':    {'execute': plugin.migrate,
                          'description': plugin.DESCRIPTIONS['migrate'],
                          'source': 'builtin'},
    'plugin:enable':     {'execute': plugin.enable,
                          'description': plugin.DESCRIPTIONS['enable'],
                          'source': 'builtin'},
    'plugin:disable':    {'execute': plugin.disable,
                          'description': plugin.DESCRIPTIONS['disable'],
                          'source': 'builtin'},
    'plugin:uninstall':  {'execute': plugin.uninstall,
                          'description': plugin.DESCRIPTIONS['uninstall'],
                          'source': 'builtin'},
    'make:migration':    {'execute': make_migration.execute,
                          'description': make_migration.DESCRIPTION,
                          'source': 'builtin'},
'plugin:check': {
'execute': plugin.check,
    'description': plugin.DESCRIPTIONS['check'],
    'source': 'builtin',
},
'plugin:upgrade': {
    'execute': plugin.upgrade,
    'description': plugin.DESCRIPTIONS['upgrade'],
    'source': 'builtin',
},
'plugin:reload': {
    'execute': plugin.reload,
    'description': plugin.DESCRIPTIONS['reload'],
    'source': 'builtin',
},
'make:plugin': {
        'execute': make_plugin.execute,
        'description': make_plugin.DESCRIPTION,
        'source': 'builtin',
    },
'plugin:install': {
    'execute': plugin.install,
    'description': "Установить плагин из файла, URL или git",
    'source': 'builtin',
},
'plugin:remove': {
    'execute': plugin.remove,
    'description': "Удалить плагин (опционально с данными)",
    'source': 'builtin',
},
'plugin:downgrade': {
    'execute': plugin.downgrade,
    'description': "Откатить плагин к указанной версии",
    'source': 'builtin',
},
'plugin:audit': {
    'execute': plugin.audit,
    'description': "Аудит установленных плагинов и миграций",
    'source': 'builtin',
},
'plugin:scaffold-upgrade': {
        'execute': scaffold_upgrade.execute,
        'description': scaffold_upgrade.DESCRIPTION,
        'source': 'builtin',
    },
'plugin:diff': {
    'execute': plugin.diff,
    'description': "Diff плагина относительно lock/git",
    'source': 'builtin',
},
'plugin:sign': {
    'execute': plugin.sign,
    'description': "Подписать плагин ed25519-ключом",
    'source': 'builtin',
},
'plugin:verify': {
    'execute': plugin.verify,
    'description': "Проверить подпись плагина",
    'source': 'builtin',
},
'plugin:keygen': {
    'execute': plugin.keygen,
    'description': "Сгенерировать ed25519-ключи для подписи",
    'source': 'builtin',
},
'plugin:search': {
    'execute': plugin.search,
    'description': "Поиск плагинов в marketplace",
    'source': 'builtin',
},
'plugin:market': {
    'execute': plugin.info_registry,
    'description': "Информация о плагине из marketplace",
    'source': 'builtin',
},
}
