# Bamboo Specs

## Требования

- Bamboo 9.2+ (для YAML Specs) или 7.x+ (для Java Specs).
- Плагин **Bamboo Specs** включён.

## Установка

### YAML (рекомендуется)

1. Скопировать `bamboo.yaml` в `bamboo-specs/` вашего репозитория.
2. В Bamboo UI: **Create → Plan → Bamboo Specs Repository**.
3. Указать URL репозитория и ветку `main`.
4. Bamboo сам создаст/обновит план `HOMER-CI` при push в `main`.

### Java

1. Скопировать `PlanSpec.java` в `bamboo-specs/src/main/java/...`.
2. Добавить `pom.xml` или `build.gradle` в `bamboo-specs/`.
3. Запустить публикацию:
   ```bash
   cd bamboo-specs
   mvn -q compile exec:java
