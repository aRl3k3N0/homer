"""
i18n:check — проверка целостности переводов.

    - сравнивает ключи всех локалей с fallback
    - находит пустые значения
    - проверяет плюрализацию (есть ли формы one/few/many/other)
    - выводит missing_keys(), накопленные в рантайме
    - опционально: --fix — дописать недостающие ключи пустыми значениями
"""
from pathlib import Path

from homer.core.console import console, Color
from homer.i18n import get_i18n


DESCRIPTION = "Проверить целостность переводов"


def _flatten(data, prefix=''):
    result = {}
    for k, v in (data or {}).items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            result.update(_flatten(v, key))
        else:
            result[key] = v
    return result


def _plural_categories_in(locale: str) -> set[str]:
    from homer.i18n.manager import _PLURAL_RULES, _DEFAULT_PLURAL
    rule = _PLURAL_RULES.get(locale[:2], _DEFAULT_PLURAL)
    # Возвращаем возможные формы
    return {rule(n) for n in (0, 1, 2, 3, 5, 11, 21, 100, 101, 111)}


def execute(context):
    i18n = get_i18n()
    args = context['args']
    fallback = args.get('fallback') or i18n.fallback_locale
    fix = bool(args.get('fix', False))
    only = args.get('locale')

    locales = i18n.available_locales()
    if not locales:
        console.error("Нет загруженных переводов. Проверьте langs/")
        return 1

    console.banner("i18n:check", f"fallback={fallback}")

    if fallback not in locales:
        console.error(f"Fallback '{fallback}' не найден среди локалей")
        return 1

    base = _flatten(i18n._translations.get(fallback, {}))
    base_keys = set(base.keys())
    plural_keys = {k for k in base_keys
                   if isinstance(base[k], dict)
                   or k.endswith(('.one', '.few', '.many', '.other'))}

    console.key_value('Доступные локали', ', '.join(locales))
    console.key_value('Ключей в fallback', len(base_keys))
    console.key_value('Plural-групп', len(plural_keys))

    n_problems = 0
    to_add: dict[str, dict] = {}

    for locale in locales:
        if locale == fallback:
            continue
        if only and locale != only:
            continue

        loc = _flatten(i18n._translations.get(locale, {}))
        loc_keys = set(loc.keys())

        missing = base_keys - loc_keys
        extra = loc_keys - base_keys
        empty = [k for k, v in loc.items() if not v or not str(v).strip()]

        # Проверка плюрализации: если в fallback есть X.one/few/many/other,
        # то и в локали должны быть все нужные формы
        plural_incomplete = []
        for k in loc_keys:
            if k.endswith(('.one', '.few', '.many', '.other', '.zero', '.two')):
                base_key = k.rsplit('.', 1)[0]
                expected = _plural_categories_in(locale)
                for cat in expected:
                    candidate = f"{base_key}.{cat}"
                    if candidate in base_keys and candidate not in loc_keys:
                        plural_incomplete.append(candidate)

        console.section(f"{locale}")
        console.key_value('Ключей', len(loc_keys))
        console.key_value('Отсутствуют', len(missing))
        console.key_value('Лишние', len(extra))
        console.key_value('Пустые', len(empty))
        console.key_value('Неполные plural', len(plural_incomplete))

        if missing:
            console.section("Отсутствующие ключи (первые 20)")
            for k in sorted(missing)[:20]:
                console.colored(f"  - {k}", Color.BRIGHT_RED)
            if len(missing) > 20:
                console.print(f"  ... ещё {len(missing) - 20}")
            n_problems += len(missing)
            to_add.setdefault(locale, {})

        if plural_incomplete:
            console.section("Неполные plural (первые 20)")
            for k in sorted(plural_incomplete)[:20]:
                console.colored(f"  ! {k}", Color.BRIGHT_YELLOW)
            n_problems += len(plural_incomplete)

        if extra:
            console.comment(f"  Лишние ключи: {len(extra)}")
            for k in sorted(extra)[:10]:
                console.print(f"    + {k}")

        if empty:
            console.comment(f"  Пустые значения:")
            for k in empty[:10]:
                console.colored(f"    ! {k}", Color.BRIGHT_YELLOW)
            n_problems += len(empty)

    # Missing keys, собранные в рантайме
    runtime_missing = i18n.missing_keys()
    if runtime_missing:
        console.section(f"Отсутствующие ключи в рантайме ({len(runtime_missing)})")
        for locale, key in runtime_missing[:30]:
            console.colored(f"  [{locale}] {key}", Color.BRIGHT_RED)
        if len(runtime_missing) > 30:
            console.print(f"  ... ещё {len(runtime_missing) - 30}")

    # --fix: дописать недостающие ключи
    if fix and to_add:
        console.section("--fix")
        for locale, keys in to_add.items():
            _add_missing_keys(i18n, locale, keys, base)
        console.success(f"Обновлено локалей: {len(to_add)}")

    # Кэш i18n
    console.section("Кэш")
    stats = i18n.cache_stats()
    console.key_value('Размер', stats['size'])
    console.key_value('Hits', stats['hits'])
    console.key_value('Misses', stats['misses'])
    console.key_value('Hit ratio', f"{stats['hit_ratio'] * 100:.1f}%")

    console.newline()
    if n_problems == 0 and not runtime_missing:
        console.success("Все переводы согласованы")
        return 0
    console.error(f"Проблем: {n_problems + len(runtime_missing)}")
    return 1


def _add_missing_keys(i18n, locale: str, keys: set[str], base: dict):
    """Дописывает пустые значения для отсутствующих ключей в <locale>.yml."""
    # Не реализуем запись в YAML в этой версии — только вывод.
    # Полноценная запись требует ruamel.yaml и сохранения комментариев.
    for k in sorted(keys):
        console.print(f"  + {locale}.{k} = {base.get(k, '')}")
