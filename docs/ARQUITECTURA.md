# Arquitectura técnica

## Flujo principal

1. Celery Beat agenda de forma independiente el scraper y Creators API.
2. Redis enruta el scraper a la cola `scraper` y la API a `creators_api`.
3. `worker_scraper` usa el perfil persistente de Playwright mientras
   `worker_creators` consulta Amazon por lotes; ambos pueden ejecutarse en paralelo.
4. Cada motor normaliza sus observaciones y las entrega al mismo servicio central.
5. Cada resultado genera un `ProductCheck`; los productos no visibles quedan como
   estado desconocido.
6. La política exige botón de mover al carrito visible, precio objetivo,
   transición de estado, cooldown, reducción significativa y límite diario.
7. Se registra una alerta enviada, omitida o fallida y, cuando corresponde, se
   publica mediante Telegram Bot API.

## Límites de responsabilidad

- `monitor/scraper.py`: navegación y conversión de HTML a datos normalizados.
- `monitor/services.py`: auditoría, disponibilidad y reglas de alerta.
- `monitor/telegram.py`: único punto de integración con Telegram.
- `monitor/tasks.py`: entrada para procesamiento en segundo plano.
- Django Admin: gestión operativa y consulta del historial.

## Seguridad y operación

El perfil de Amazon contiene una sesión autenticada y debe tratarse como un
secreto. Está excluido de Git y solo debe montarse en `worker_scraper`. El sistema no
presiona botones ni modifica el carrito.

Cada worker usa concurrencia uno. El paralelismo ocurre entre motores, mientras
`worker_scraper` impide que dos navegadores utilicen simultáneamente el mismo
perfil. Las reservas transaccionales coordinan ambos procesos cuando detectan el
mismo producto.
