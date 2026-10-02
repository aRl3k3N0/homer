from lib.i18n import t, set_locale, get_i18n

# Простой перевод
print(t('common.save'))                          # "Сохранить"

# С подстановкой
print(t('mail.welcome.greeting', user='Иван'))   # "Здравствуйте, Иван!"

# Временно другая локаль
old = get_i18n().locale
set_locale('en')
print(t('common.save'))                          # "Save"
set_locale(old)

# Явно указать локаль для одного вызова
print(t('common.save', locale='en'))             # "Save"



#comang
from lib.i18n import t

def execute(context):
    args = context['args']
    name = args.get('name', 'world')
    print(t('hello.greeting', name=name))
    return 0
