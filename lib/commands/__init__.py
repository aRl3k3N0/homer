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
from . import migrate
from . import make_plugin
from . import scaffold_upgrade
from . import webui_service, schedule_service
from . import logs_clean
from . import user
from . import i18n_check
from . import registry
from . import config_cache
from . import i18n_cache
from . import paths_info


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
        'description': 'Internal command for subprocess mode',
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
    'migrate': {
        'execute': migrate.execute,
        'description': migrate.DESCRIPTION,
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
        'description': "Install the plugin from a file, URL, or git.",
        'source': 'builtin',
    },
    'plugin:remove': {
        'execute': plugin.remove,
        'description': "Remove the plugin (optionally with data)",
        'source': 'builtin',
    },
    'plugin:downgrade': {
        'execute': plugin.downgrade,
        'description': "Roll back the plugin to the specified version.",
        'source': 'builtin',
    },
    'plugin:audit': {
        'execute': plugin.audit,
        'description': "Audit of installed plugins and migrations",
        'source': 'builtin',
    },
    'plugin:scaffold-upgrade': {
            'execute': scaffold_upgrade.execute,
            'description': scaffold_upgrade.DESCRIPTION,
            'source': 'builtin',
        },
    'plugin:diff': {
        'execute': plugin.diff,
        'description': "Diff of the plugin relative to lock/git",
        'source': 'builtin',
    },
    'plugin:sign': {
        'execute': plugin.sign,
        'description': "Sign the plugin with an ed25519 key.",
        'source': 'builtin',
    },
    'plugin:verify': {
        'execute': plugin.verify,
        'description': "Verify the plugin signature",
        'source': 'builtin',
    },
    'plugin:keygen': {
        'execute': plugin.keygen,
        'description': "Generate ed25519 keys for signing.",
        'source': 'builtin',
    },
    'plugin:search': {
        'execute': plugin.search,
        'description': "Search for plugins in the marketplace",
        'source': 'builtin',
    },
    'plugin:market': {
        'execute': plugin.info_registry,
        'description': "Information about the plugin from marketplace",
        'source': 'builtin',
    },
    # Web UI
    'webui:start': {
        'execute': webui_service.start,
        'description': webui_service.DESCRIPTIONS['start'],
        'source': 'builtin',
    },
    'webui:stop': {
        'execute': webui_service.stop,
        'description': webui_service.DESCRIPTIONS['stop'],
        'source': 'builtin',
    },
    'webui:restart': {
        'execute': webui_service.restart,
        'description': webui_service.DESCRIPTIONS['restart'],
        'source': 'builtin',
    },
    'webui:reload': {
        'execute': webui_service.reload,
        'description': webui_service.DESCRIPTIONS['reload'],
        'source': 'builtin',
    },
    'webui:status': {
        'execute': webui_service.status,
        'description': webui_service.DESCRIPTIONS['status'],
        'source': 'builtin',
    },
    'webui:logs': {
        'execute': webui_service.logs,
        'description': webui_service.DESCRIPTIONS['logs'],
        'source': 'builtin',
    },
    '_webui_run': {
        'execute': webui_service._run,
        'description': 'Внутренняя команда: сервер Web UI',
        'source': 'builtin',
    },

    # Scheduler
    'schedule:start': {
        'execute': schedule_service.start,
        'description': schedule_service.DESCRIPTIONS['start'],
        'source': 'builtin',
    },
    'schedule:stop': {
        'execute': schedule_service.stop,
        'description': schedule_service.DESCRIPTIONS['stop'],
        'source': 'builtin',
    },
    'schedule:restart': {
        'execute': schedule_service.restart,
        'description': schedule_service.DESCRIPTIONS['restart'],
        'source': 'builtin',
    },
    'schedule:reload': {
        'execute': schedule_service.reload,
        'description': schedule_service.DESCRIPTIONS['reload'],
        'source': 'builtin',
    },
    'schedule:status': {
        'execute': schedule_service.status,
        'description': schedule_service.DESCRIPTIONS['status'],
        'source': 'builtin',
    },
    'schedule:logs': {
        'execute': schedule_service.logs,
        'description': schedule_service.DESCRIPTIONS['logs'],
        'source': 'builtin',
    },
    '_schedule_run': {
        'execute': schedule_service._run,
        'description': 'Внутренняя команда: планировщик',
        'source': 'builtin',
    },
    'services': {
        'execute': schedule_service.services_status,
        'description': "Статус всех сервисов Homer",
        'source': 'builtin',
    },
    'logs:clean': {
        'execute': logs_clean.execute,
        'description': logs_clean.DESCRIPTION,
        'source': 'builtin',
    },
    'user:list': {'execute': user.list_users, 'description': user.DESCRIPTIONS['list'], 'source': 'builtin'},
    'user:create': {'execute': user.create_user, 'description': user.DESCRIPTIONS['create'], 'source': 'builtin'},
    'user:passwd': {'execute': user.passwd, 'description': user.DESCRIPTIONS['passwd'], 'source': 'builtin'},
    'user:enable': {'execute': user.enable, 'description': user.DESCRIPTIONS['enable'], 'source': 'builtin'},
    'user:disable': {'execute': user.disable, 'description': user.DESCRIPTIONS['disable'], 'source': 'builtin'},
    'user:delete': {'execute': user.delete_user, 'description': user.DESCRIPTIONS['delete'], 'source': 'builtin'},
    'user:roles': {'execute': user.roles, 'description': user.DESCRIPTIONS['roles'], 'source': 'builtin'},
    'user:grant': {'execute': user.grant, 'description': user.DESCRIPTIONS['grant'], 'source': 'builtin'},
    'user:revoke': {'execute': user.revoke, 'description': user.DESCRIPTIONS['revoke'], 'source': 'builtin'},

    'role:list': {'execute': user.role_list, 'description': 'Список ролей', 'source': 'builtin'},
    'role:show': {'execute': user.role_show, 'description': 'Показать роль', 'source': 'builtin'},
    'role:create': {'execute': user.role_create, 'description': 'Создать роль', 'source': 'builtin'},
    'role:edit': {'execute': user.role_edit, 'description': 'Изменить роль', 'source': 'builtin'},
    'role:delete': {'execute': user.role_delete, 'description': 'Удалить роль', 'source': 'builtin'},
    'perm:list': {'execute': user.perm_list, 'description': 'Список прав', 'source': 'builtin'},

    'i18n:check': {
        'execute': i18n_check.execute,
        'description': i18n_check.DESCRIPTION,
        'source': 'builtin',
    },
    "registry:info": {
        "execute": registry.info,
        "description": registry.DESCRIPTIONS["info"],
        "source": "builtin",
    },
    "registry:clear": {
        "execute": registry.clear,
        "description": registry.DESCRIPTIONS["clear"],
        "source": "builtin",
    },
    "registry:rebuild": {
        "execute": registry.rebuild,
        "description": registry.DESCRIPTIONS["rebuild"],
        "source": "builtin",
    },
    "registry:bench": {
        "execute": registry.bench,
        "description": registry.DESCRIPTIONS["bench"],
        "source": "builtin",
    },
    "registry:cache": {
        "execute": registry.cache,
        "description": registry.DESCRIPTIONS["cache"],
        "source": "builtin",
    },
    "config:cache": {
        "execute": config_cache.cache,
        "description": config_cache.DESCRIPTIONS["cache"],
        "source": "builtin",
    },
    "config:rebuild": {
        "execute": config_cache.rebuild,
        "description": config_cache.DESCRIPTIONS["rebuild"],
        "source": "builtin",
    },
    "config:clear": {
        "execute": config_cache.clear,
        "description": config_cache.DESCRIPTIONS["clear"],
        "source": "builtin",
    },
    "config:info": {
        "execute": config_cache.info,
        "description": config_cache.DESCRIPTIONS["info"],
        "source": "builtin",
    },
    "i18n:cache": {
        "execute": i18n_cache.cache,
        "description": i18n_cache.DESCRIPTIONS["cache"],
        "source": "builtin",
    },
    "i18n:rebuild": {
        "execute": i18n_cache.rebuild,
        "description": i18n_cache.DESCRIPTIONS["rebuild"],
        "source": "builtin",
    },
    "i18n:clear": {
        "execute": i18n_cache.clear,
        "description": i18n_cache.DESCRIPTIONS["clear"],
        "source": "builtin",
    },
    "i18n:info": {
        "execute": i18n_cache.info,
        "description": i18n_cache.DESCRIPTIONS["info"],
        "source": "builtin",
    },
    "paths:info": {
        "execute": paths_info.execute,
        "description": paths_info.DESCRIPTION,
        "source": "builtin",
    },
}
