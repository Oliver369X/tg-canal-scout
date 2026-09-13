# Canal Scout

Proyecto independiente. En v1 usa las claves Telegram de AURA Intelligence (solo local, el `.env` no se sube).

## Qué hace

Pegás o reenviás un canal al bot. Te responde ficha de lo reciente (fotos/videos/peso/fecha/links) **sin bajar videos**.

- **Bot:** te habla en el celular.
- **Tu cuenta (Telethon):** lee el canal. Si la sesión no está logueada, hay que hacer login **una vez**.

## Arranque local (Docker)

1. `.env` ya se puede generar copiando TELEGRAM_* de AURA.
2. Login (solo si `/status` dice no autorizado):

```
docker compose --profile login run --rm login
```

3. Bot:

```
docker compose up --build
```

En Telegram: `/start` al bot, después un `t.me/canal` o un post reenviado.

## Sin Docker

```
pip install -r requirements.txt
python -m app.login
python -m app.main
```
