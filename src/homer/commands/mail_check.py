"""
Проверка настройки почтового транспорта.
"""
from homer.core.console import console


DESCRIPTION = "Check the mailer settings."


def execute(context):
    from homer.core.mailer import Mailer

    config = context['config']
    root_dir = context['root_dir']

    try:
        mailer = Mailer(config, root_dir / 'email')
    except Exception as e:
        console.error(f"Failed to initialize mailer: {e}")
        return 1

    console.section("Mailer")
    console.key_value('Transport', mailer.transport_name)
    console.key_value('From',
                      f"{mailer.default_from_name} <{mailer.default_from}>")
    console.key_value('Templates', str(mailer.templates_dir))

    ok, message = mailer.check()
    if ok:
        console.success(message)
    else:
        console.error(message)
        return 1

    templates = mailer.list_templates()
    if templates:
        console.section("Available templates")
        for t in templates:
            console.list_item(t)
    else:
        console.warning("No templates found.")

    return 0
