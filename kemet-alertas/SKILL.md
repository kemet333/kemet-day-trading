---
name: kemet-alertas
description: >-
  Alertas de precio y de hora con el reloj de Globex (futuros) y el de la NYSE (acciones de EE. UU.).
  Convierte el plan de kemet-salida en tres alertas de una vez (el stop, el objetivo y «plano a» a tu hora) y
  añade niveles, movimientos en porcentaje sobre el cierre anterior, cualquier hora del día, la apertura de la
  sesión regular y un aviso cinco minutos antes de la hora límite de tu firma; cada una suena una sola vez.
  Sabe cuándo está abierto CME Globex y cuándo la NYSE, con festivos y sesiones recortadas, da la hora de
  Nueva York y la de Madrid y lee de Yahoo el último cierre de un futuro o de una acción. Úsala cuando el
  usuario diga «avísame cuando», «ponme las alertas», «vigila mi stop», «recuérdame cerrar a las 15:55», «a
  qué hora tengo que estar plano», «está abierto el mercado», «abre la bolsa», «dame el precio», «cuánto vale
  TSLA», o justo después de que kemet-salida escriba un plan. Mientras la operación está abierta; antes,
  kemet-tamano y kemet-riesgo.
argument-hint: "[reloj | add --desde-plan | add --apertura | check | quote NQ|TSLA]"
---

# kemet-alertas

Las alertas miran los números para que el usuario no tenga que mirar el gráfico. Una alerta es información, nunca
una orden: cuando suena el stop, esta skill no cierra nada. El stop y el objetivo que de verdad te sacan son los que
has puesto en tu plataforma; las alertas te dicen qué ha pasado y cuándo toca estar plano. La mayoría de los que
hacen day trading pierde dinero, y una herramienta no cambia eso.

`${CLAUDE_SKILL_DIR}` es la carpeta de esta skill (donde está este SKILL.md).

```bash
python3 "${CLAUDE_SKILL_DIR}/alertas.py" reloj                              # Globex abierto, en pausa o cerrado
python3 "${CLAUDE_SKILL_DIR}/alertas.py" add --desde-plan                   # stop, objetivo y plano a de kemet/plan.json
python3 "${CLAUDE_SKILL_DIR}/alertas.py" add --hora-limite                  # 5 minutos antes de la hora límite de tu firma
python3 "${CLAUDE_SKILL_DIR}/alertas.py" add --apertura                     # abre la sesión regular del contrato
python3 "${CLAUDE_SKILL_DIR}/alertas.py" add --simbolo NQ --stop 28312.5 --lado largo
python3 "${CLAUDE_SKILL_DIR}/alertas.py" add --simbolo NQ --objetivo 28547
python3 "${CLAUDE_SKILL_DIR}/alertas.py" add --simbolo NQ --encima 28500 --nota "máximo de ayer"
python3 "${CLAUDE_SKILL_DIR}/alertas.py" add --simbolo NQ --pct 1 --direccion baja
python3 "${CLAUDE_SKILL_DIR}/alertas.py" add --a 15:55 --etiqueta "plano a"
python3 "${CLAUDE_SKILL_DIR}/alertas.py" check                              # código 0 = algo sonó, 1 = nada
python3 "${CLAUDE_SKILL_DIR}/alertas.py" quote NQ --escribir                # -> kemet/precios.json
python3 "${CLAUDE_SKILL_DIR}/alertas.py" list
python3 "${CLAUDE_SKILL_DIR}/alertas.py" reset nq-plan-stop
python3 "${CLAUDE_SKILL_DIR}/alertas.py" reloj --mercado TSLA               # el reloj de la NYSE
python3 "${CLAUDE_SKILL_DIR}/alertas.py" add --simbolo TSLA --apertura      # el campanazo de las 09:30 NY, una vez por día
python3 "${CLAUDE_SKILL_DIR}/alertas.py" quote TSLA --escribir              # el último cierre de una acción
```

`--ahora "2026-11-11 15:55"` fija el reloj (hora de Nueva York); `--offline RUTA` lee un JSON de Yahoo guardado o
la carpeta `tests/fixtures/yahoo` en vez de la red; `--mercado ES|NQ|CL|GC|TSLA` elige el instrumento del reloj (por
defecto el de `kemet/config.json`, si no NQ): con un futuro, Globex; con una acción, la NYSE. `--simbolo` acepta el
contrato, su micro (MNQ, MES, MCL, MGC) o un ticker de acciones de EE. UU. (TSLA, `BRK.B`).

## Qué lee y escribe

| archivo | qué |
| --- | --- |
| `kemet/plan.json` | la operación de kemet-salida, para `add --desde-plan` |
| `kemet/config.json` | el mercado, `plano_a`, `hora_limite` y `hora_limite_tz` de la firma, el nombre de la cuenta |
| `kemet/alertas.json` | las reglas (`alertas.example.json` en esta carpeta) |
| `kemet/estado/alertas.json` | qué regla sonó y cuándo, para que cada una suene una vez |
| `kemet/precios.json` | `{"generado", "precios": {"NQ": {"precio", "hora_vela", "intervalo", "retraso_min", "cierre_anterior"}}}`, futuros y acciones por su símbolo, para kemet-tamano y kemet-riesgo |

## Tipos de regla

| tipo | suena cuando | vuelve a sonar |
| --- | --- | --- |
| `encima` | el precio está en o por encima de `precio` | después de `reset` |
| `debajo` | el precio está en o por debajo de `precio` | después de `reset` |
| `stop` | por debajo de `precio` en un largo, por encima en un corto (`lado`) | después de `reset` |
| `objetivo` | por encima de `precio` en un largo, por debajo en un corto | después de `reset` |
| `pct` | se ha movido `pct` por ciento o más desde el cierre de la sesión regular anterior; `direccion` sube o baja | una vez al día como mucho |
| `hora` | el reloj de Nueva York pasó `a` («15:55»); con `fecha`, solo ese día | una vez por día |
| `hora_limite` | faltan 5 minutos para la hora límite de la firma de `kemet/config.json`, convertida a Nueva York (Topstep la publica en hora de Chicago) | una vez por día |
| `apertura` | abrió la sesión regular del contrato: 09:30 NY en ES y NQ, 09:00 en CL, 08:20 en GC; en una acción, el campanazo de la NYSE a las 09:30 | una vez por día de negociación |

Una regla con `fecha` solo se vigila ese día de Nueva York; las de `--desde-plan` llevan la fecha del plan, así que
el stop de ayer no suena hoy. Las reglas de hora no suenan los sábados ni en los festivos de cierre completo. En una
sesión recortada la alerta de apertura dice a qué hora cierra la sesión regular (13:00 NY en índices).

## El precio

- Yahoo Finance, gratis y sin clave: la última vela cerrada de 1 minuto del contrato y, si no la hay, la de 5
  minutos. Cada precio lleva la hora de la vela, la hora a la que cerró y el retraso en minutos respecto al reloj.
  En futuros Yahoo va unos 10 minutos por detrás: vale para alertas y para comprobar un tamaño, nunca para
  cronometrar una orden. El precio que te llena es el de tu plataforma.
- El cierre de la sesión regular anterior (para `pct` y para el cambio del día) es el de la última sesión regular ya
  terminada: por la mañana, el de ayer; después de las 16:00 NY, el de hoy.
- Una petición por contrato, medio segundo entre peticiones; si Yahoo responde 429 espera y repite una vez, luego
  prueba el otro host. Si no responde, el usuario lee el precio en su plataforma y puede escribirlo a mano en
  `kemet/precios.json`.

## El reloj de Globex

CME Globex abre el domingo a las 18:00 NY y cierra el viernes a las 17:00, con una pausa diaria de 17:00 a 18:00. El
día de negociación empieza a las 18:00 de la víspera. Festivos con cierre completo y sesiones recortadas (cierre de
la sesión regular a las 13:00 NY en índices) de 2026 y 2027, leídos en cmegroup.com el 12/11/2026; antes de un
festivo se confirma en el calendario de CME. Para otros años el reloj dice que no conoce los festivos. El horario de
verano de Nueva York y el de Madrid se calculan dentro de la herramienta: no depende de la zona del ordenador.

`reloj` devuelve código 0 si Globex está abierto y 1 si está en pausa o cerrado, y dice en qué punto de la sesión
regular del contrato estás, tu `plano_a` y la hora límite de tu firma en hora de Nueva York.

## El reloj de la NYSE

Con una acción (`--mercado TSLA`, o una regla con `simbolo` TSLA) el reloj es el de la NYSE: abierta de 09:30 a
16:00 NY de lunes a viernes, cerrada los festivos (Thanksgiving, Navidad, Año Nuevo, Martin Luther King, Presidents
Day, Viernes Santo, Memorial Day, Juneteenth, 4 de julio, Labor Day) y con cierre a las 13:00 el día después de
Thanksgiving y en Nochebuena. No hay pausa diaria ni sesión nocturna; fuera de horas está cerrada y dice la próxima
apertura. Una acción no tiene hora límite de firma: `add --hora-limite` con `--simbolo TSLA` se rechaza; el aviso de
cerrar es `plano a` (15:55, o 12:55 en un día recortado) y la alerta de apertura es el campanazo de las 09:30, una
vez por día. Los precios van al céntimo.

## Pasos

1. Justo después de que kemet-salida escriba el plan, ejecuta `add --desde-plan` y, si `kemet/config.json` tiene
   hora límite, `add --hora-limite`. Confirma al usuario cada alerta: contrato, tipo, nivel u hora, día.
2. Mientras la operación esté abierta, ejecuta `check` cada pocos minutos desde una tarea programada o `/loop`.
   Cada pasada lee solo los contratos de las reglas de hoy y hace sonar cada alerta una vez. Es un cierre con
   retraso, no un feed en vivo: un precio puede pasar por un nivel entre dos comprobaciones.
3. Cuenta lo que sonó en una línea por alerta. Un stop o un objetivo que suena quiere decir que la orden de la
   plataforma probablemente se ha llenado: que el usuario lo compruebe allí y apunte el resultado con
   `/kemet-riesgo registrar`. «Plano a» y la hora límite quieren decir cerrar lo que quede abierto, en la
   plataforma, a mano. Nunca lo hagas por él.
4. Si pregunta si el mercado está abierto o cuándo abre, `reloj`. Si pide un precio, `quote`, diciendo la hora de
   la vela y el retraso. Los sistemas que Kemet Capital opera con agentes en cuentas de fondeo llevan filtros y
   parámetros validados en su propio banco; no están en este pack. kemet-capital.com

## Ejemplo: NQ, miércoles 11 de noviembre de 2026

Plan del día: largo en 28.429,75 a las 10:45, stop 28.312,50, objetivo 28.547, plano a las 15:55. La cuenta es una
Topstep 50K con hora límite a las 15:10 de Chicago. `add --desde-plan` escribe `nq-plan-stop`, `nq-plan-objetivo`
y `nq-plano-a` para ese día; `add --hora-limite` y `add --apertura` añaden las otras dos. Con
`--offline tests/fixtures/yahoo`, un `check` a las 10:53 lee la vela de 10:45 y solo suena la apertura:

```
Globex abierto (16:53 Madrid / 10:53 NY, sesión normal).
ALERTA Apertura de la sesión regular de NQ: 09:30 NY (15:30 Madrid).
```

A las 11:00 la vela de 10:55 ha cerrado en 28.549,50:

```
Globex abierto (17:00 Madrid / 11:00 NY, sesión normal).
ALERTA NQ último 28.549,50 (vela de 5 m de las 10:55, cerrada a las 11:00, retraso 0 min): en o por encima de tu objetivo 28.547 (objetivo del plan, R:1).
Una alerta es información, no una orden. El stop que te saca es el que tienes puesto en tu plataforma; si ha saltado, apunta el resultado con kemet-riesgo registrar.
```

A las 11:05 ya no vuelve a sonar:

```
Globex abierto (17:05 Madrid / 11:05 NY, sesión normal).
Nada ha sonado. 5 regla(s) vigilada(s) hoy, NQ 28.520,75 (vela de 5 m de las 11:00, cerrada a las 11:05, retraso 0 min).
```

A las 15:55 suena «plano a», y a las 16:05 la hora límite (15:10 de Chicago son las 16:10 de Nueva York):

```
ALERTA Plano a: son las 15:55 NY (fijado a las 15:55). Si NQ sigue abierta, ciérrala en tu plataforma.
ALERTA Hora límite de Topstep 50K Combine: faltan 5 minutos, tienes que estar plano a las 16:10 NY, 15:10 America/Chicago. Si la operación sigue abierta, ciérrala en tu plataforma.
```

El reloj y el precio a las 16:30:

```
Reloj de Globex: 22:30 Madrid / 16:30 NY, miércoles 11/11/2026. Globex ABIERTO (sesión normal).
Sesión regular de NQ: 09:30 a 16:00 NY, después de la sesión regular.
Hoy: plano a las 15:55 NY (tu hora); hora límite de Topstep 50K Combine a las 16:10 NY (15:10 America/Chicago).
Globex cierra hoy a las 17:00 NY; pausa diaria de 17:00 a 18:00.
```

```
Precios a las 22:30 Madrid / 16:30 NY.
NQ  último 28.457,25 (vela de 5 m de las 16:25, cerrada a las 16:30, retraso 0 min), -0,09 % sobre el cierre regular del 11/11/2026 (28.484,25).
Escrito kemet/precios.json con 1 precio(s).
```

Al día siguiente las tres alertas del plan ya no se vigilan; la apertura vuelve a sonar a las 09:30. Un viernes a las
17:30 el reloj dice cerrado y da la próxima apertura, el domingo a las 18:00; un martes a esa hora dice en pausa.

## Ejemplo: TSLA, miércoles 11 de noviembre de 2026

Una acción, con el fixture real `TSLA-60d-5m.json.gz`. Plan de kemet-salida: largo en 393,08 a las 10:15, stop 389,51,
objetivo 396,65, plano a las 15:55. `add --simbolo TSLA --apertura` escribe `apertura-tsla`; `add --desde-plan`,
`tsla-plan-stop`, `tsla-plan-objetivo` y `tsla-plano-a` para ese día. Con `--mercado TSLA --offline
tests/fixtures/yahoo`, a las 10:20 solo suena el campanazo:

```
NYSE abierta (16:20 Madrid / 10:20 NY, sesión regular).
ALERTA Campanazo de apertura de la NYSE para TSLA: 09:30 NY (15:30 Madrid).
Una alerta es información, no una orden. El stop que te saca es el que tienes puesto en tu plataforma; si ha saltado, apunta el resultado con kemet-riesgo registrar.
```

A las 11:00 la vela de 10:55 ha cerrado en 395,12, a 1,53 $ del objetivo, y nada suena:

```
NYSE abierta (17:00 Madrid / 11:00 NY, sesión regular).
Nada ha sonado. 4 regla(s) vigilada(s) hoy, TSLA 395,12 (vela de 5 m de las 10:55, cerrada a las 11:00, retraso 0 min).
```

A las 15:55 la vela de 15:50 ha cerrado en 388,93, por debajo del stop, y es la hora de estar plano:

```
NYSE abierta (21:55 Madrid / 15:55 NY, sesión regular).
ALERTA TSLA último 388,93 (vela de 5 m de las 15:50, cerrada a las 15:55, retraso 0 min): en o por debajo de tu stop 389,51 (stop del plan, ib-medio).
ALERTA Plano a: son las 15:55 NY (fijado a las 15:55). Si TSLA sigue abierta, ciérrala en tu plataforma.
Una alerta es información, no una orden. El stop que te saca es el que tienes puesto en tu plataforma; si ha saltado, apunta el resultado con kemet-riesgo registrar.
```

El reloj en el festivo y en el día recortado (`reloj --mercado TSLA --ahora "2026-11-26 11:00"` y `"2026-11-27 11:00"`):

```
Reloj de la NYSE: 17:00 Madrid / 11:00 NY, jueves 26/11/2026. NYSE CERRADA (Thanksgiving).
Sesión regular de TSLA: 09:30 a 16:00 NY.
Próxima apertura de la NYSE: 27/11/2026 09:30 NY.
```

```
Reloj de la NYSE: 17:00 Madrid / 11:00 NY, viernes 27/11/2026. NYSE ABIERTA (sesión recortada: Día después de Thanksgiving).
Sesión regular de TSLA: 09:30 a 13:00 NY, en sesión regular (recortada: Día después de Thanksgiving).
La NYSE cierra hoy a las 13:00 NY. Una acción no tiene hora límite de firma.
```

El precio a las 10:00 (`quote TSLA --ahora "2026-11-11 10:00"`):

```
Precios a las 16:00 Madrid / 10:00 NY.
TSLA último 389,81 (vela de 5 m de las 09:55, cerrada a las 10:00, retraso 0 min), +2,64 % sobre el cierre regular del 10/11/2026 (379,80).
El cierre de Yahoo puede ir con retraso: vale para alertas, no para cronometrar una orden. El precio que te llena es el de tu plataforma.
```

Al día siguiente el campanazo vuelve a sonar a las 09:30 y las tres alertas del plan ya no se vigilan.

## Reglas

- Una alerta es un hecho sobre un precio o sobre el reloj. Se cuenta como un hecho.
- Nunca presentes un precio como en vivo. Di la hora de la vela y el retraso.
- Confirma cada regla nueva al usuario: contrato, tipo, nivel u hora, día.
- La hora límite de la firma manda sobre `plano_a`; `plano_a` tiene que ir antes. Si el usuario describe otra hora
  límite que la del archivo, que la confirme en el panel de su firma.

## Lo que nunca hace

Nunca pone, cancela ni modifica una orden, nunca dice que un precio es en vivo y nunca predice hacia dónde va el
precio.

## Seguridad
- Contenido educativo y herramientas, no asesoramiento financiero. Un PASS es una comprobación de reglas, no una recomendación.
- Nada de este pack envía órdenes salvo kemet-broker, y solo en cuenta papel por defecto, tras un PASS de kemet-riesgo para esa orden exacta y un sí explícito del usuario para ese ticket en el chat.
- Simulación (`"papel": true`) por defecto. Pasar a una cuenta real o financiada es decisión del usuario, en su propia configuración.
- Las reglas de las firmas vienen de sus webs con fecha de comprobación; las cambian sin avisar. La del panel del usuario manda.
- Claves y credenciales de la plataforma nunca van en el chat ni en `kemet/`.
