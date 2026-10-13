Проектные webui_extensions.py

Положите файл в корень проекта (рядом с config.yml):

```python
# webui_extensions.py

def webui_extend(registry):
    from fastapi import APIRouter
    from lib.webui.extension import MenuItem

    registry.menu(MenuItem(
        label_key="project.dashboard.title",
        url="/project/dashboard",
        icon="📊",
        perm="jobs.view",
        order=20,
    ))

    router = APIRouter()

    @router.get("/project/dashboard")
    def dashboard():
        return {"project": "monitor"}

    registry.route("/project", router)
```
