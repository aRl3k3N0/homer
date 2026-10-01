Notify
======

Базовые классы
--------------

.. automodule:: lib.notify.base
   :members:
   :show-inheritance:

Менеджер
--------

.. autoclass:: lib.notify.NotifyManager
   :members:

Нотификаторы
------------

.. autoclass:: lib.notify.EmailNotifier
   :members:

.. autoclass:: lib.notify.FileNotifier
   :members:

.. autoclass:: lib.notify.LogNotifier
   :members:

.. autoclass:: lib.notify.DesktopNotifier
   :members:

.. autoclass:: lib.notify.TelegramNotifier
   :members:

.. autoclass:: lib.notify.SlackNotifier
   :members:

.. autoclass:: lib.notify.MattermostNotifier
   :members:

Реестр
------

.. data:: lib.notify.REGISTRY
   :type: dict[str, type[lib.notify.base.BaseNotifier]]

   Доступные нотификаторы по имени.
