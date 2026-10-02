"""
Права и роли по умолчанию.
"""

PERM_JOBS_VIEW     = 'jobs.view'
PERM_JOBS_CANCEL   = 'jobs.cancel'
PERM_JOBS_RETRY    = 'jobs.retry'
PERM_JOBS_PURGE    = 'jobs.purge'
PERM_QUEUE_PUSH    = 'queue.push'
PERM_SCHED_VIEW    = 'schedule.view'
PERM_SCHED_EDIT    = 'schedule.edit'
PERM_LOGS_VIEW     = 'logs.view'
PERM_LOGS_DOWNLOAD = 'logs.download'
PERM_LOGS_CLEAN    = 'logs.clean'
PERM_CONSOLE_USE   = 'console.use'
PERM_HISTORY_VIEW  = 'history.view'
PERM_USERS_MANAGE  = 'users.manage'
PERM_ROLES_MANAGE  = 'roles.manage'
PERM_SYSTEM_VIEW   = 'system.view'
PERM_SYSTEM_ADMIN  = 'system.admin'

ALL_PERMISSIONS = {
    PERM_JOBS_VIEW, PERM_JOBS_CANCEL, PERM_JOBS_RETRY, PERM_JOBS_PURGE,
    PERM_QUEUE_PUSH,
    PERM_SCHED_VIEW, PERM_SCHED_EDIT,
    PERM_LOGS_VIEW, PERM_LOGS_DOWNLOAD, PERM_LOGS_CLEAN,
    PERM_CONSOLE_USE, PERM_HISTORY_VIEW,
    PERM_USERS_MANAGE, PERM_ROLES_MANAGE,
    PERM_SYSTEM_VIEW, PERM_SYSTEM_ADMIN,
}


BUILTIN_ROLES = {
    'admin': {
        'display_name': 'Administrator',
        'permissions': sorted(ALL_PERMISSIONS),
    },
    'operator': {
        'display_name': 'Operator',
        'permissions': [
            PERM_JOBS_VIEW, PERM_JOBS_CANCEL, PERM_JOBS_RETRY,
            PERM_QUEUE_PUSH,
            PERM_SCHED_VIEW, PERM_SCHED_EDIT,
            PERM_LOGS_VIEW, PERM_LOGS_DOWNLOAD,
            PERM_CONSOLE_USE, PERM_HISTORY_VIEW,
            PERM_SYSTEM_VIEW,
        ],
    },
    'viewer': {
        'display_name': 'Observer',
        'permissions': [
            PERM_JOBS_VIEW, PERM_SCHED_VIEW,
            PERM_LOGS_VIEW, PERM_HISTORY_VIEW,
            PERM_SYSTEM_VIEW,
        ],
    },
}
