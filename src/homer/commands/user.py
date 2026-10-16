"""
Команды управления пользователями и ролями.

    user:list
    user:create   --username=X [--password=Y] [--role=viewer] [--display=...] [--email=...]
    user:passwd   --username=X [--password=Y]   (без --password — интерактивно)
    user:enable   --username=X
    user:disable  --username=X
    user:delete   --username=X
    user:roles    --username=X
    user:grant    --username=X --role=operator
    user:revoke   --username=X --role=operator

    role:list
    role:create   --name=X --permissions=a,b,c [--display=...]
    role:delete   --name=X
    role:edit     --name=X [--permissions=a,b,c] [--display=...]
    role:show     --name=X
    perm:list
"""
from pathlib import Path

from homer.core.console import console, Color


DESCRIPTIONS = {
    'list':    "Список пользователей",
    'create':  "Создать пользователя",
    'passwd':  "Сменить пароль",
    'enable':  "Включить пользователя",
    'disable': "Отключить пользователя",
    'delete':  "Удалить пользователя",
    'roles':   "Роли пользователя",
    'grant':   "Назначить роль пользователю",
    'revoke':  "Снять роль с пользователя",
}


def _store(context):
    from homer.auth import AuthStore
    return AuthStore(context['config'])


# ─────────── Пользователи ───────────

def list_users(context):
    store = _store(context)
    try:
        users = store.list_users()
        if not users:
            console.warning("Пользователей нет")
            return 0
        rows = [
            [
                u.id, u.username, u.display_name or '—', u.email or '—',
                u.provider,
                console.colored('да', Color.BRIGHT_GREEN) if u.enabled
                else console.colored('нет', Color.BRIGHT_RED),
                ', '.join(u.roles) or '—',
            ]
            for u in users
        ]
        console.table(
            headers=['ID', 'Логин', 'Имя', 'Email', 'Провайдер',
                     'Активен', 'Роли'],
            rows=rows,
            align=['r', 'l', 'l', 'l', 'l', 'c', 'l'],
        )
        return 0
    finally:
        store.close()


def create_user(context):
    args = context['args']
    username = args.get('username')
    password = args.get('password')
    if not username:
        console.error("Укажите --username")
        return 1

    if not password:
        password = console.ask("Пароль для нового пользователя", default='')
        if not password:
            console.error("Пароль не может быть пустым")
            return 1

    store = _store(context)
    try:
        if store.get_user_by_name(username):
            console.error(f"Пользователь '{username}' уже существует")
            return 1
        uid = store.create_user(
            username,
            password=password,
            display_name=args.get('display', ''),
            email=args.get('email', ''),
            provider=args.get('provider', 'local'),
        )
        role = args.get('role', 'viewer')
        if role and store.get_role(role):
            store.assign_role(uid, role)
        console.success(f"Пользователь '{username}' создан (id={uid})")
        return 0
    finally:
        store.close()


def passwd(context):
    args = context['args']
    username = args.get('username')
    if not username:
        console.error("Укажите --username")
        return 1
    password = args.get('password')
    if not password:
        password = console.ask(f"Новый пароль для {username}", default='')
        if not password:
            console.error("Пароль не может быть пустым")
            return 1
    store = _store(context)
    try:
        if not store.get_user_by_name(username):
            console.error(f"Пользователь '{username}' не найден")
            return 1
        store.set_password(username, password)
        console.success(f"Пароль для '{username}' обновлён")
        return 0
    finally:
        store.close()


def enable(context):
    return _toggle(context, True)


def disable(context):
    return _toggle(context, False)


def _toggle(context, enabled):
    username = context['args'].get('username')
    if not username:
        console.error("Укажите --username")
        return 1
    store = _store(context)
    try:
        if not store.get_user_by_name(username):
            console.error(f"Пользователь '{username}' не найден")
            return 1
        store.set_enabled(username, enabled)
        console.success(f"Пользователь '{username}' "
                        f"{'включён' if enabled else 'отключён'}")
        return 0
    finally:
        store.close()


def delete_user(context):
    username = context['args'].get('username')
    if not username:
        console.error("Укажите --username")
        return 1
    if not console.confirm(f"Удалить '{username}'?", default=False):
        console.comment("Отменено")
        return 0
    store = _store(context)
    try:
        if not store.delete_user(username):
            console.error(f"Пользователь '{username}' не найден")
            return 1
        console.success(f"Пользователь '{username}' удалён")
        return 0
    finally:
        store.close()


def roles(context):
    username = context['args'].get('username')
    if not username:
        console.error("Укажите --username")
        return 1
    store = _store(context)
    try:
        u = store.get_user_by_name(username)
        if not u:
            console.error(f"Пользователь '{username}' не найден")
            return 1
        console.banner(f"Роли пользователя {u.username}")
        if not u.roles:
            console.warning("Роли не назначены")
            return 0
        for r in u.roles:
            console.list_item(r)
        return 0
    finally:
        store.close()


def grant(context):
    args = context['args']
    username = args.get('username')
    role = args.get('role')
    if not username or not role:
        console.error("Укажите --username и --role")
        return 1
    store = _store(context)
    try:
        u = store.get_user_by_name(username)
        if not u:
            console.error(f"Пользователь '{username}' не найден")
            return 1
        if not store.assign_role(u.id, role):
            console.error(f"Роль '{role}' не найдена или уже назначена")
            return 1
        console.success(f"Роль '{role}' назначена '{username}'")
        return 0
    finally:
        store.close()


def revoke(context):
    args = context['args']
    username = args.get('username')
    role = args.get('role')
    if not username or not role:
        console.error("Укажите --username и --role")
        return 1
    store = _store(context)
    try:
        u = store.get_user_by_name(username)
        if not u:
            console.error(f"Пользователь '{username}' не найден")
            return 1
        store.revoke_role(u.id, role)
        console.success(f"Роль '{role}' снята с '{username}'")
        return 0
    finally:
        store.close()


# ─────────── Роли ───────────

def role_list(context):
    store = _store(context)
    try:
        roles = store.list_roles()
        rows = [
            [
                r['name'],
                r['display_name'] or '—',
                console.colored('да', Color.BRIGHT_CYAN) if r['builtin']
                else 'нет',
                len(r['permissions']),
            ]
            for r in roles
        ]
        console.table(
            headers=['Роль', 'Отображение', 'Встроенная', 'Прав'],
            rows=rows,
            align=['l', 'l', 'c', 'r'],
        )
        return 0
    finally:
        store.close()


def role_show(context):
    name = context['args'].get('name')
    if not name:
        console.error("Укажите --name")
        return 1
    store = _store(context)
    try:
        r = store.get_role(name)
        if not r:
            console.error(f"Роль '{name}' не найдена")
            return 1
        console.banner(f"Роль: {r['name']}", r['display_name'] or '')
        console.key_value('Встроенная', 'да' if r['builtin'] else 'нет')
        console.section("Права")
        for p in sorted(r['permissions']):
            console.list_item(p)
        return 0
    finally:
        store.close()


def role_create(context):
    args = context['args']
    name = args.get('name')
    if not name:
        console.error("Укажите --name")
        return 1
    perms_raw = args.get('permissions', '')
    perms = [p.strip() for p in str(perms_raw).split(',') if p.strip()]
    store = _store(context)
    try:
        if store.get_role(name):
            console.error(f"Роль '{name}' уже существует")
            return 1
        store.upsert_role(
            name,
            display_name=args.get('display', ''),
            permissions=perms,
            builtin=False,
        )
        console.success(f"Роль '{name}' создана")
        return 0
    finally:
        store.close()


def role_edit(context):
    args = context['args']
    name = args.get('name')
    if not name:
        console.error("Укажите --name")
        return 1
    store = _store(context)
    try:
        r = store.get_role(name)
        if not r:
            console.error(f"Роль '{name}' не найдена")
            return 1
        perms_raw = args.get('permissions')
        if perms_raw is not None:
            perms = [p.strip() for p in str(perms_raw).split(',') if p.strip()]
        else:
            perms = r['permissions']
        store.upsert_role(
            name,
            display_name=args.get('display', r['display_name']),
            permissions=perms,
            builtin=r['builtin'],
        )
        console.success(f"Роль '{name}' обновлена")
        return 0
    finally:
        store.close()


def role_delete(context):
    name = context['args'].get('name')
    if not name:
        console.error("Укажите --name")
        return 1
    store = _store(context)
    try:
        if not store.delete_role(name):
            console.error(f"Роль '{name}' не найдена или встроенная")
            return 1
        console.success(f"Роль '{name}' удалена")
        return 0
    finally:
        store.close()


def perm_list(context):
    from homer.auth.permissions import ALL_PERMISSIONS
    console.banner("Права Homer")
    for p in sorted(ALL_PERMISSIONS):
        console.list_item(p)
    return 0
