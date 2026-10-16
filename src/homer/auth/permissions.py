# ─────────── Existing ───────────
PERM_JOBS_VIEW       = 'jobs.view'
PERM_JOBS_CANCEL     = 'jobs.cancel'
PERM_JOBS_RETRY      = 'jobs.retry'
PERM_JOBS_PURGE      = 'jobs.purge'
PERM_QUEUE_PUSH      = 'queue.push'
PERM_SCHED_VIEW      = 'schedule.view'
PERM_SCHED_EDIT      = 'schedule.edit'
PERM_LOGS_VIEW       = 'logs.view'
PERM_LOGS_DOWNLOAD   = 'logs.download'
PERM_LOGS_CLEAN      = 'logs.clean'
PERM_CONSOLE_USE     = 'console.use'
PERM_HISTORY_VIEW    = 'history.view'
PERM_HISTORY_VIEW_ALL= 'history.view.all'
PERM_USERS_MANAGE    = 'users.manage'
PERM_ROLES_MANAGE    = 'roles.manage'
PERM_SYSTEM_VIEW     = 'system.view'
PERM_SYSTEM_ADMIN    = 'system.admin'

# ─────────── Editor ───────────
PERM_EDITOR_VIEW          = 'editor.view'            # see the Editor section
PERM_EDITOR_CONFIG        = 'editor.config'          # edit config.yml / includes
PERM_EDITOR_COMMANDS      = 'editor.commands'        # edit user commands
PERM_EDITOR_PLUGINS       = 'editor.plugins'         # edit plugin code
PERM_EDITOR_PLUGINS_ADMIN = 'editor.plugins.admin'   # enable/disable/install/remove plugins
PERM_EDITOR_LANGS         = 'editor.langs'           # edit translations
PERM_EDITOR_TEMPLATES     = 'editor.templates'       # edit Web UI templates
PERM_EDITOR_STATIC        = 'editor.static'          # edit Web UI static files

# ─────────── Extensibility ───────────
PERM_MENU_MANAGE     = 'menu.manage'                 # register custom menu items
PERM_ROUTES_MANAGE   = 'routes.manage'               # register custom routers


ALL_PERMISSIONS = {
    PERM_JOBS_VIEW, PERM_JOBS_CANCEL, PERM_JOBS_RETRY, PERM_JOBS_PURGE,
    PERM_QUEUE_PUSH,
    PERM_SCHED_VIEW, PERM_SCHED_EDIT,
    PERM_LOGS_VIEW, PERM_LOGS_DOWNLOAD, PERM_LOGS_CLEAN,
    PERM_CONSOLE_USE,
    PERM_HISTORY_VIEW, PERM_HISTORY_VIEW_ALL,
    PERM_USERS_MANAGE, PERM_ROLES_MANAGE,
    PERM_SYSTEM_VIEW, PERM_SYSTEM_ADMIN,
    # Editor
    PERM_EDITOR_VIEW, PERM_EDITOR_CONFIG, PERM_EDITOR_COMMANDS,
    PERM_EDITOR_PLUGINS, PERM_EDITOR_PLUGINS_ADMIN,
    PERM_EDITOR_LANGS, PERM_EDITOR_TEMPLATES, PERM_EDITOR_STATIC,
    # Extensibility
    PERM_MENU_MANAGE, PERM_ROUTES_MANAGE,
}


BUILTIN_ROLES = {
    'admin': {
        'display_name': 'Administrator',
        'permissions': sorted(ALL_PERMISSIONS),
    },
    'developer': {
        'display_name': 'Developer',
        'permissions': [
            PERM_JOBS_VIEW, PERM_QUEUE_PUSH,
            PERM_SCHED_VIEW, PERM_SCHED_EDIT,
            PERM_LOGS_VIEW, PERM_LOGS_DOWNLOAD,
            PERM_CONSOLE_USE,
            PERM_HISTORY_VIEW, PERM_HISTORY_VIEW_ALL,
            PERM_SYSTEM_VIEW,
            # Editor (without plugin admin)
            PERM_EDITOR_VIEW, PERM_EDITOR_CONFIG, PERM_EDITOR_COMMANDS,
            PERM_EDITOR_LANGS, PERM_EDITOR_TEMPLATES,
            PERM_MENU_MANAGE, PERM_ROUTES_MANAGE,
        ],
    },
    'translator': {
        'display_name': 'Translator',
        'permissions': [
            PERM_LOGS_VIEW, PERM_HISTORY_VIEW,
            PERM_EDITOR_VIEW, PERM_EDITOR_LANGS,
        ],
    },
    'operator': {  # unchanged, keep as you had
        'display_name': 'Operator',
        'permissions': [
            PERM_JOBS_VIEW, PERM_JOBS_CANCEL, PERM_JOBS_RETRY,
            PERM_QUEUE_PUSH,
            PERM_SCHED_VIEW, PERM_SCHED_EDIT,
            PERM_LOGS_VIEW, PERM_LOGS_DOWNLOAD,
            PERM_CONSOLE_USE,
            PERM_HISTORY_VIEW,
            PERM_SYSTEM_VIEW,
        ],
    },
    'viewer': {  # unchanged
        'display_name': 'Viewer',
        'permissions': [
            PERM_JOBS_VIEW, PERM_SCHED_VIEW,
            PERM_LOGS_VIEW, PERM_HISTORY_VIEW,
            PERM_SYSTEM_VIEW,
        ],
    },
}
