---
name: kemet-salida
description: >-
  El stop y el objetivo antes de entrar, para saber cuándo salir. Lee el
  disparo de kemet-entrada (o un precio que le des), pone el stop en el punto
  medio del balance inicial por defecto (o en el lado opuesto, en tu precio, a
  X puntos o a K veces el ATR), lo redondea al tick y pone el objetivo a 1R (o
  2R, o tu precio). Da el riesgo en puntos y en dólares por micro y por mini y
  la hora de estar plano, respetando la hora límite de la firma. Rechaza con
  motivo un stop del lado equivocado, un objetivo detrás de la entrada, un
  riesgo de menos de 4 ticks o una entrada fuera de horas. Escribe
  kemet/plan.json para kemet-maquina, kemet-tamano, kemet-riesgo y
  kemet-alertas. Nunca envía una orden. Úsala cuando el usuario diga "dónde
  pongo el stop", "stop y objetivo", "plan de salida", "cuándo salgo", "cuánto
  arriesgo", "qué R tiene", "ratio riesgo beneficio", o justo después de que
  kemet-entrada dispare, antes de kemet-maquina.
argument-hint: "plan [--stop ib-medio|ib-opuesto|pts:X|precio:X|atr:K] [--objetivo R:1|R:2|precio:X] [--plano-a HH:MM] [--escribir] | show"
---

# kemet-salida

Decide cómo termina una operación antes de que empiece. El stop es donde la ruptura ha dejado de serlo. El
objetivo es donde te llevas lo que venías a buscar. Los dos se fijan ANTES de la entrada, se escriben y se pasan
a las siguientes skills, para que nadie tenga que decidir nada en mitad de un movimiento rápido. Un stop es un
plan, no una garantía: un hueco o un mercado rápido lo pueden llenar más allá. La mayoría de los que hacen day
trading pierde dinero, y una herramienta no cambia eso.

`${CLAUDE_SKILL_DIR}` es la carpeta de esta skill (donde vive este SKILL.md).

```bash
python3 "${CLAUDE_SKILL_DIR}/salida.py" plan                                 # desde kemet/entrada.json: stop en el medio del IB, objetivo 1R
python3 "${CLAUDE_SKILL_DIR}/salida.py" plan --escribir                      # y guarda kemet/plan.json
python3 "${CLAUDE_SKILL_DIR}/salida.py" plan --stop ib-opuesto --objetivo R:2
python3 "${CLAUDE_SKILL_DIR}/salida.py" plan --stop atr:1.5                  # necesita las velas de la sesión (Yahoo o --offline)
python3 "${CLAUDE_SKILL_DIR}/salida.py" plan --entrada 28429.75 --lado largo --ib-alto 28426 --ib-bajo 28199 --hora 10:45
python3 "${CLAUDE_SKILL_DIR}/salida.py" show                                 # el kemet/plan.json actual
```

Otros flags: `--plano-a 15:30`, `--json`, `--ahora "AAAA-MM-DD HH:MM"` (hora de Nueva York), `--mercado`,
`--fecha`, `--barra` (para el ATR), `--de RUTA` (otro entrada.json), `--offline RUTA` (un JSON de Yahoo guardado o
la carpeta `tests/fixtures/yahoo`, para un stop por ATR). `--entrada PRECIO --lado largo|corto` con un
entrada.json que aún está esperando planifica por adelantado al precio que esperas.

## Qué lee y escribe

| archivo | qué |
| --- | --- |
| `kemet/entrada.json` | el disparo de kemet-entrada: mercado, lado, precio, hora, barra, IB (alto, bajo, minutos) |
| `kemet/config.json` | `plano_a` (15:55), `hora_limite` y `hora_limite_tz` de la firma, `sin_entradas_despues` (15:00), `max_mini` (si es 0 no se habla de minis). Opcional: sin él usa los valores del contrato y lo dice |
| Yahoo Finance | solo para un stop `atr:K`: las velas de la sesión hasta la de la entrada, gratis y sin clave |
| `kemet/plan.json` | con `--escribir`: entrada, stop y su regla, objetivo y su regla, riesgo en puntos y en dólares por micro y por mini, ratio, hora de estar plano, IB. Lo leen kemet-maquina, kemet-tamano, kemet-riesgo y kemet-alertas |

## Stops y objetivos

| stop | dónde va |
| --- | --- |
| `ib-medio` | el punto medio del IB (por defecto): si el precio vuelve ahí, la ruptura ha fallado |
| `ib-opuesto` | el lado opuesto del IB: más ancho, así que menos contratos para la misma pérdida máxima |
| `pts:X` | X puntos detrás de la entrada |
| `precio:X` | tu precio |
| `atr:K` | K veces el ATR de 14 velas, con las velas de la sesión regular hasta la de la entrada; con menos de 14 velas promedia las que hay y lo dice |

| objetivo | dónde va |
| --- | --- |
| `R:1` | una vez el riesgo desde la entrada (por defecto) |
| `R:2` | dos veces el riesgo; vale cualquier `R:X` |
| `precio:X` | tu precio, y te dice cuántas R son |

- **Al tick.** Stop y objetivo se redondean al tick del contrato (0,25 en ES y NQ, 0,01 en CL, 0,10 en GC).
  Riesgo = distancia de la entrada al stop, en puntos; en dólares, por el valor del punto del micro (2 $ en MNQ,
  5 $ en MES, 100 $ en MCL, 10 $ en MGC) y del mini.
- **Rechazado, con el motivo.** Un stop al nivel de la entrada o del lado equivocado. Un objetivo al nivel de la
  entrada o detrás. Un riesgo de menos de 4 ticks: demasiado pegado para el ruido normal. Una entrada posterior
  a `sin_entradas_despues` o a la hora de estar plano o después. Un entrada.json que no ha disparado (salvo que des
  `--entrada` y `--lado`).
- **Plano a.** `--plano-a`, si no `plano_a` del config, si no la del contrato (15:55 en índices, 14:25 en CL,
  13:25 en GC). Nunca después de la hora límite de la firma menos 5 minutos (`hora_limite` en su zona, Chicago en
  Topstep) ni del cierre de una sesión recortada menos 5 minutos. Fuera a esa hora, gane o pierda.

## Pasos

1. Ejecútala justo después de que kemet-entrada dispare. Antes, `--entrada PRECIO --lado` planifica por
   adelantado al nivel que esperas.
2. Deja el stop por defecto salvo que el usuario nombre otro. Si pide uno más ancho, dile que son menos contratos
   para la misma pérdida máxima; kemet-tamano lo calcula.
3. Ejecuta `salida.py plan --escribir`. Léele la entrada, el stop y su regla, el objetivo y su regla, el riesgo
   en puntos y en dólares por micro, el ratio y la hora de estar plano.
4. Si rechaza, di el motivo y el arreglo (un stop más lejos, un objetivo más lejos). Nunca aflojes nada por tu
   cuenta.
5. Di una vez que el stop es un plan, no una garantía.
6. Pasa a kemet-maquina para repetir el plan sobre sesiones pasadas y a kemet-tamano para convertirlo en
   contratos. Ofrece kemet-alertas para el stop, el objetivo y la hora de estar plano.
7. Los sistemas que Kemet Capital opera con agentes en cuentas de fondeo llevan filtros y parámetros validados en
   su propio banco; no están en este pack. kemet-capital.com

## Ejemplo: NQ, miércoles 11 de noviembre de 2026

Con `--offline tests/fixtures/yahoo`. kemet-entrada disparó largo a las 10:45 en 28.429,75 (la vela de 10:40,
barra 15) con un IB de 28.199 a 28.426. `salida.py plan --escribir --ahora "2026-11-11 10:46"`:

```
Plan de salida: NQ largo, miércoles 11/11/2026, ruptura del IB de 60 minutos sobre velas de 5 minutos
  Entrada   28.429,75 a las 10:45 NY (barra 15)
  Stop      28.312,50  punto medio del IB: (28.426 + 28.199) / 2
  Objetivo  28.547  1 R (1 vez el riesgo): 28.429,75 + 1 x 117,25
  Riesgo    117,25 puntos, 234,50 $ por micro (MNQ), 2.345 $ por mini (NQ)
  Recorrido 117,25 puntos hasta el objetivo, 1 vez el riesgo
  Plano a las 21:55 Madrid / 15:55 NY, gane o pierda: nada se queda abierto
  IB        28.199 a 28.426, 227 puntos
Stop y objetivo van puestos antes de la entrada. Si el precio toca el stop, fuera; el stop nunca se aleja.
Un stop es un plan, no una garantía: un hueco o un mercado rápido lo pueden llenar más allá.
Sin kemet/config.json: plano a las 15:55 del contrato y sin hora límite de firma.
Escrito kemet/plan.json.
Siguiente: kemet-maquina lo repite sobre sesiones pasadas y kemet-tamano lo convierte en contratos. No se ha enviado ninguna orden.
```

Con `--stop ib-opuesto --objetivo R:2` el stop baja a 28.199 (230,75 puntos, 461,50 $ por micro) y el objetivo
sube a 28.891,25. Con `--stop atr:1.5 --offline tests/fixtures/yahoo` el ATR de las 14 velas hasta la entrada es
69,18 puntos y el stop queda en 28.326 (103,75 puntos, 207,50 $ por micro), objetivo 1R en 28.533,50. Con
`--stop precio:28500` rechaza: el stop de un largo va debajo de la entrada. Con un config de Apex con
`hora_limite` 15:50 NY, el plano se adelanta a las 15:45 y lo dice en una nota.

## Reglas

- El stop y el objetivo se fijan antes de la entrada, nunca después.
- Un stop nunca se aleja de la entrada una vez abierta la operación.
- Solo cifras llanas: entrada, stop, objetivo, riesgo en puntos y en dólares, ratio. Nunca imprime un P&L ni una
  rentabilidad esperada.
- Un objetivo a 1R no es una predicción de que el precio llegue.
- Largo y corto. Igual en ES, NQ, CL y GC.

## Lo que nunca hace

Nunca envía una orden, nunca calcula contratos (eso es kemet-tamano), nunca ensancha un stop para que un plan
pase y nunca llama garantía a un stop.

## Seguridad
- Contenido educativo y herramientas, no asesoramiento financiero. Un PASS es una comprobación de reglas, no una recomendación.
- Nada de este pack envía órdenes a ningún bróker ni a ninguna firma de fondeo. Las operaciones las pone el usuario en su plataforma, con su stop.
- Simulación (`"papel": true`) por defecto. Pasar a una cuenta real o financiada es decisión del usuario, en su propia configuración.
- Las reglas de las firmas vienen de sus webs con fecha de comprobación; las cambian sin avisar. La del panel del usuario manda.
- Claves y credenciales de la plataforma nunca van en el chat ni en `kemet/`.
