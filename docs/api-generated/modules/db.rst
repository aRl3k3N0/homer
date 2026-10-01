Database
========

Базовый класс
-------------

.. automodule:: lib.db.base
   :members:
   :show-inheritance:

Драйверы
--------

.. autoclass:: lib.db.SQLiteDB
   :members:
   :show-inheritance:

.. autoclass:: lib.db.PostgresDB
   :members:
   :show-inheritance:

.. autoclass:: lib.db.OracleDB
   :members:
   :show-inheritance:

Утилиты
-------

.. autofunction:: lib.db.connect
.. autofunction:: lib.db.get_driver

Реестр
------

.. data:: lib.db.DRIVERS
   :type: dict[str, type[lib.db.BaseDB]]

   Доступные драйверы по имени.
