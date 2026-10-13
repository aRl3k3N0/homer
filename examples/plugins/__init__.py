"""
Плагины
"""

def plugin_init(context):
    from lib.auth import AuthStore, BUILTIN_ROLES

    # Register permissions
    from lib.auth import permissions
    permissions.ALL_PERMISSIONS.add("notes.view")
    permissions.ALL_PERMISSIONS.add("notes.edit")

    # Grant to admin role
    store = AuthStore(context["config"])
    admin = store.get_role("admin")
    if admin:
        perms = set(admin["permissions"]) | {"notes.view", "notes.edit"}
        store.upsert_role("admin",
                          display_name=admin["display_name"],
                          permissions=sorted(perms),
                          builtin=admin["builtin"])
    store.close()

def webui_extend(registry):
    """
    Called during Web UI startup if the plugin is enabled.
    """
    from fastapi import APIRouter, Depends
    from lib.webui.extension import MenuItem
    from pathlib import Path
    registry.template_dir(Path(__file__).parent / "templates")

    # Menu entry
    registry.menu(MenuItem(
        label_key="notes.menu.title",       # i18n key
        url="/notes",
        icon="📝",
        perm="notes.view",
        order=50,
        group="main",
    ))

    # Custom routes
    router = APIRouter()

    @router.get("/notes")
    def notes_index():
        return {"ok": True, "plugin": "notes"}

    @router.get("/notes/{note_id}")
    def notes_show(note_id: int):
        return {"id": note_id}

    registry.route(
        prefix="/plugins/notes",
        router=router,
        perm="notes.view",
        source="plugin:notes",
    )
