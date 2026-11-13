---
name: kemet-maquina
description: >-
  La máquina del tiempo. Antes de arriesgar un dólar, repite el resto de la sesión 10.000 veces desde tu entrada
  con las velas de 5 minutos del propio instrumento (futuros ES, NQ, CL, GC o una acción de EE. UU. como TSLA, las
  últimas 60 sesiones de Yahoo) y vuelve a pasar la misma regla por cada sesión anterior. Toma el plan de kemet-salida (entrada, stop, objetivo, hora) o lo
  recibe por flags, y devuelve las probabilidades de objetivo primero, stop primero o ninguno a tu hora de estar
  plano, dónde queda el precio, la R media, la historia real y un veredicto en una línea; después pasa a
  kemet-tamano. Úsala cuando el usuario diga «qué probabilidad tiene», «simúlalo», «es un coin flip», «monte
  carlo», «cuántas veces llega al objetivo», «repite este día», «backtest de esta entrada», o siempre después de que
  kemet-salida escriba un plan y antes de kemet-tamano. Todo en puntos (dólares por acción en una acción) y en R;
  nunca un P&L esperado.
argument-hint: "[run | chart] [--hasta 15:55] [--semilla 19]"
---

# kemet-maquina

La máquina del tiempo va entre el plan y el dinero. kemet-salida ya ha fijado entrada, stop y objetivo. Antes de
calcular un tamaño, esta skill hace una sola pregunta: si hoy se pareciera a las últimas sesiones del propio
contrato, ¿cuántas veces este plan toca el objetivo primero, el stop primero o ninguno de los dos? Responde con
10.000 repeticiones y con lo que esa misma regla hizo de verdad en cada sesión anterior. Es una simulación hecha con
las velas recientes del contrato, no una predicción. La mayoría de los que hacen day trading pierde dinero, y una
herramienta no cambia eso.

`${CLAUDE_SKILL_DIR}` es la carpeta de esta skill (donde está este SKILL.md).

```bash
python3 "${CLAUDE_SKILL_DIR}/maquina.py" run                      # kemet/plan.json, 10.000 repeticiones, semilla 19
python3 "${CLAUDE_SKILL_DIR}/maquina.py" run --escribir           # además guarda kemet/maquina.json
python3 "${CLAUDE_SKILL_DIR}/maquina.py" run --hasta 15:55        # cada repetición termina a tu hora de estar plano
python3 "${CLAUDE_SKILL_DIR}/maquina.py" run --json
python3 "${CLAUDE_SKILL_DIR}/maquina.py" run --mercado NQ --fecha 2026-11-11 --lado largo \
    --entrada 28429.75 --stop 28312.5 --objetivo 28547 --hora-entrada 10:45
python3 "${CLAUDE_SKILL_DIR}/maquina.py" run --mercado TSLA --fecha 2026-11-11 --lado largo \
    --entrada 393.08 --stop 389.51 --objetivo 396.65 --hora-entrada 10:15      # una acción: IB de 15 minutos
python3 "${CLAUDE_SKILL_DIR}/maquina.py" chart --desde            # abanico ASCII del resultado guardado
```

Otros flags: `--repeticiones N`, `--semilla N` (19 por defecto), `--ventana N` (2 velas), `--ib-minutos 15|30|60`,
`--regla-stop ib-medio|ib-opuesto|pts:X`, `--regla-objetivo R:1|R:2`, `--offline RUTA` (un JSON de Yahoo guardado
o la carpeta `tests/fixtures/yahoo`), `--ahora "2026-11-11 16:30"` (hora de Nueva York) para fijar el reloj.

## Qué lee y escribe

| archivo | qué |
| --- | --- |
| `kemet/plan.json` | el plan de kemet-salida: mercado, fecha, lado, entrada, hora_entrada o barra, stop, regla_stop, objetivo, regla_objetivo, plano_a, ib |
| `kemet/config.json` | si existe: el mercado por defecto, `sin_entradas_antes`, `sin_entradas_despues`, `plano_a` |
| Yahoo Finance | una petición: 60 días de velas de 5 minutos del contrato, gratis, sin clave, con retraso |
| `kemet/maquina.json` | con `--escribir`: `{plan, mc, historia, veredicto, notas, avisos}`. `mc` lleva las probabilidades, los percentiles, las bandas del abanico, 160 caminos y un histograma de 24 cajas del precio final |

## Cómo funciona

1. **El pool.** Solo sesiones regulares completas del instrumento anteriores a la fecha del plan: NQ y ES las 78
   velas de 09:30 a 16:00 NY, CL 66, GC 62, por día de negociación de CME; una acción de EE. UU., las 78 velas de
   09:30 a 16:00 por fecha de Nueva York, sin noche y con los precios de Yahoo al céntimo. Las recortadas, las que
   tienen huecos y la de hoy se quedan fuera. Cada vela se convierte en cuatro ratios sobre el cierre de la vela
   anterior: apertura, máximo, mínimo y cierre.
2. **Una repetición.** Arranca en tu precio de entrada. Para cada vela que queda de sesión elige al azar una vela
   pasada de la misma hora del día (más o menos 2 velas) y la escala al precio actual. Vela a vela comprueba primero
   el stop y después el objetivo: una vela que toca los dos cuenta como stop. En un corto el stop está por encima y
   el objetivo por debajo.
3. **10.000 repeticiones** dan cuatro cifras. Objetivo primero. Stop primero. Ninguno: la operación sigue abierta a
   `--hasta` (por defecto `plano_a` del plan: 15:55 en índices, 14:25 en CL, 13:25 en GC). Verde: objetivo primero
   o por encima de la entrada a esa hora (por debajo en un corto). R vale +1 en un objetivo a 1R, -1 en el stop y,
   si no, la distancia desde la entrada a `--hasta` dividida entre el riesgo. Un hueco a través del stop cuenta -1R
   aquí; un relleno real puede ser peor.
4. **La historia.** La regla del plan, tal cual, en cada una de esas sesiones: balance inicial de los mismos
   minutos (60 por defecto en futuros, 15 en una acción), disparo en la primera vela de 5 minutos cerrada después del IB que cierra por encima
   del IB alto (largo) o por debajo del IB bajo (corto), entrada en ese cierre, sin entradas antes de las 09:45 ni
   después de las 15:00 (o lo que diga el plan o `kemet/config.json`), stop según `regla_stop` (punto medio del IB
   por defecto, lado opuesto, puntos fijos), objetivo según `regla_objetivo` (1R por defecto, 2R), plano a `--hasta`.
   Sin filtro: cuentan todas las sesiones en las que disparó, una operación por día, los dos lados. Un stop o un
   objetivo a un precio fijo (`precio:X`) no se puede repetir en otros días: se usa la distancia del plan en puntos y
   se dice. Eso es lo que pasó de verdad, no una simulación.
5. **El veredicto** es una línea que sale de los números. Mira solo las repeticiones que tocan un lado y pregunta
   cuántas veces llegó antes el objetivo. Un objetivo más lejano necesita ganar menos veces para empatar: 1 entre
   (1 + R), el 50 % a 1R, el 33 % a 2R, el 25 % a 3R. A menos de 5 puntos del empate: «Casi una moneda al aire» a
   1R, «Casi en el punto de equilibrio» con otra R. De 5 a 15 puntos: «Se inclina hacia el objetivo» o «Se inclina
   hacia el stop». 15 o más: «Claramente hacia» uno de los dos. Antes de eso, la máquina repite la simulación 30
   veces con las sesiones remuestreadas (otras 45 o 60 sesiones igual de plausibles) y saca el intervalo del 90 % de
   esa parte: si el empate cae dentro, el veredicto es «No se distingue de una moneda al aire» (o «del punto de
   equilibrio»), diga lo que diga la cifra suelta. La historia lleva su intervalo del 90 % (Wilson): 14 objetivos
   contra 13 stops no dicen nada. Un plan a 2R con objetivo primero 24 % y stop
   primero 50 % está casi en el punto de equilibrio (necesita el 33 % de las que tocan un lado y tiene el 32 %), no
   es un plan perdedor.
6. **Debajo del veredicto**, cuando toca: una línea si más del 40 % de las repeticiones no toca ningún lado (el
   precio a `--hasta` decide esas), y la R media cuando su signo va contra la inclinación. Solo pueden apuntar en
   otra dirección por las repeticiones que no tocan nada.

**La semilla.** Las tiradas salen de `random.Random(semilla)`, 19 por defecto. Mismo plan, mismos datos, misma
semilla: los mismos números en cualquier máquina. Di la semilla con cada resultado para que el usuario pueda repetirlo.

**Las velas.** `hora_entrada` es la hora a la que cierra la vela del disparo y `barra` su número desde la apertura
(la vela 1 cierra a las 09:35; la 15, a las 10:45). Las repeticiones empiezan en la vela siguiente. Si el plan no
trae hora, se simula desde la primera vela después del IB y se avisa. Solo velas de 5 minutos: Yahoo guarda 60 días
en 5 minutos y unos 7 en 1 minuto, pocas sesiones para un pool justo. Rechaza en una línea con menos de 20 sesiones
completas, con una entrada fuera de la rejilla de 5 minutos o después de `--hasta`, o con un stop del lado
equivocado. Nunca usa una vela que no ha cerrado ni mezcla las velas de hoy en el pool.

## Pasos

1. Comprueba que `kemet/plan.json` es el plan de hoy de `/kemet-salida`. Si no existe, pásalo primero o da el plan
   por flags.
2. Ejecuta `maquina.py run --escribir`. `--hasta` toma `plano_a` del plan; cámbialo solo si el usuario va a salir
   antes, para que «ninguno» signifique abierta a la hora a la que saldría de verdad.
3. Cuéntale al usuario, en este orden: las cuatro cifras, la mediana y el tramo del 90 % del precio final, la R
   media, la línea de la historia, y el veredicto con las líneas de debajo tal cual salen. Di la semilla.
4. Si el veredicto es una moneda al aire o el punto de equilibrio, dilo así. No lo adornes. Si la historia y las
   repeticiones no coinciden, dilo también.
5. Di una vez que está hecho con las últimas sesiones del contrato y no es una predicción: un dato, una noticia o un
   día de pánico hacen lo que esas sesiones no hicieron. Mira la agenda del día en `/kemet-plan` antes de seguir.
6. Si el usuario sigue queriendo la operación, pasa a `/kemet-tamano` para el tamaño y a `/kemet-riesgo` para la
   comprobación. Los sistemas que Kemet Capital opera con agentes en cuentas de fondeo llevan filtros y parámetros
   validados en su propio banco; no están en este pack. kemet-capital.com

## Ejemplo: NQ, miércoles 11 de noviembre de 2026

Balance inicial de 09:30 a 10:30: 28.199 a 28.426 (227 puntos). La vela de 10:40 cierra en 28.429,75, por encima
del IB alto: entrada 28.429,75 a las 10:45 (vela 15), stop en el punto medio del IB 28.312,50 (117,25 puntos),
objetivo 1R en 28.547. Con `--offline tests/fixtures/yahoo --ahora "2026-11-11 16:30"`:

```
Máquina del tiempo de NQ, miércoles 11/11/2026 (22:30 Madrid / 16:30 NY)
NQ largo: entrada 28.429,75 a las 10:45 (vela 15), stop 28.312,50 (117,25 pts), objetivo 28.547 (117,25 pts, 1R).
1R = 117,25 pts = 234,50 $ por MNQ (2.345 $ por NQ). Es contexto del tamaño, no un resultado esperado.
10.000 repeticiones del resto de la sesión, de 10:45 a 15:55 (62 velas de 5 minutos), semilla 19.
Cada vela sale entera de las velas de 5 minutos de NQ a la misma hora del día (más o menos 2 velas) en sus últimas 46 sesiones regulares completas (03/09/2026 a 10/11/2026).

  objetivo primero   45,5 %
  stop primero       46,3 %
  ninguno            8,2 %    sigue abierta a las 15:55
  verde              49,7 %   objetivo primero, o por encima de la entrada a las 15:55

  Precio a las 15:55: mediana 28.420,61, el 90 % de las repeticiones entre 28.134,90 y 28.726,42.
  R media: -0,007 (1R = 117,25 pts; +1R en el objetivo, -1R en el stop).

Historia: la misma regla (IB de 60 minutos, primera vela cerrada fuera del IB entre las 09:45 y las 15:00, entrada en su cierre, stop en el punto medio del IB, objetivo 1R, plano a la hora de --hasta) en esas 46 sesiones reales disparó 39 veces (23 largos, 16 cortos; 7 sesiones sin cierre fuera del IB): 14 objetivo, 13 stop, 12 ninguno a las 15:55. R media +0,038. Con tan pocas, la parte del objetivo entre las que tocan un lado puede ir del 37 % al 67 % (90 %).

No se distingue de una moneda al aire: objetivo primero 45,5 % frente a stop primero 46,3 %, pero con otras sesiones igual de plausibles la parte del objetivo va del 40 % al 59 % (intervalo del 90 %) y el equilibrio, 50 %, está dentro.

Fuera del pool 2 sesión(es) corta(s) (recortadas o con huecos): 30/10/2026, 05/11/2026.
Simulación hecha con las últimas 46 sesiones completas de NQ. No es una predicción: un dato, una noticia o un día de pánico hacen lo que esas sesiones no hicieron. Misma semilla, mismos números. Repite esta corrida con --semilla 19.
```

A 1R el objetivo tiene que llegar primero en la mitad de las repeticiones que tocan un lado; llegó en el 49,6 %. Las
repeticiones salen a moneda al aire y la historia real, 14 objetivos contra 13 stops con 12 abiertas al cierre, no
dice otra cosa. Ese día la vela de 10:55 tocó 28.550,25 y el objetivo saltó al cuarto de hora; eso es un resultado,
no una prueba de nada. Es lo que el usuario tiene que oír antes de que `/kemet-tamano` calcule los micros.

`chart --desde` dibuja el abanico de 2.000 caminos con las líneas del stop y del objetivo:

```
NQ 11/11/2026, 2.000 caminos desde la entrada de las 10:45 (semilla 19)
 28.751,20 |                                                               
           |                                           ... . ... ..........
           |                     ...  .....................................
           |            ...................................................
           |         ......................................................
    28.547 |-----......................................::..........::::::..  objetivo
           |  .........::::::::::::::::::::::::::::::::::::::::::::::::::::
           | .:::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::
 28.429,75 |***************************************************************  entrada
           | ::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::
           |  ..............:::::::::::::::::::::::::::::::::::::::::::::::
 28.312,50 |-----..........................::::::::::::::::::::::::::::::::  stop
           |           ....................................................
           |                     ..........................................
           |                             ..................................
           |                                              . ...............
 28.115,46 |                                                               
           +---------------------------------------------------------------
            10:45                          13:20                      15:55
* mediana   : la mitad central de los caminos   . el 90 % de los caminos   - stop y objetivo
```

## Ejemplo: TSLA, miércoles 11 de noviembre de 2026

Una acción: balance inicial de 15 minutos, 09:30 a 09:45, 386,35 a 392,67 (6,32 $). La vela de 10:10 cierra en
393,08, por encima del IB alto: entrada 393,08 a las 10:15 (vela 9), stop en el punto medio del IB 389,51 (3,57 $ por
acción), objetivo 1R en 396,65. Con el plan de kemet-salida en `kemet/plan.json` y `--offline tests/fixtures/yahoo
--ahora "2026-11-11 16:30"`:

```
Máquina del tiempo de TSLA, miércoles 11/11/2026 (22:30 Madrid / 16:30 NY)
TSLA largo: entrada 393,08 a las 10:15 (vela 9), stop 389,51 (3,57 $), objetivo 396,65 (3,57 $, 1R).
1R = 3,57 $ por acción. Es contexto del tamaño, no un resultado esperado.
10.000 repeticiones del resto de la sesión, de 10:15 a 15:55 (68 velas de 5 minutos), semilla 19.
Cada vela sale entera de las velas de 5 minutos de TSLA a la misma hora del día (más o menos 2 velas) en sus últimas 57 sesiones regulares completas (20/08/2026 a 10/11/2026).

  objetivo primero   52,6 %
  stop primero       41,3 %
  ninguno            6,1 %    sigue abierta a las 15:55
  verde              55,6 %   objetivo primero, o por encima de la entrada a las 15:55

  Precio a las 15:55: mediana 392,99, el 90 % de las repeticiones entre 383,60 y 402,15.
  R media: +0,113 (1R = 3,57 $; +1R en el objetivo, -1R en el stop).

Historia: la misma regla (IB de 15 minutos, primera vela cerrada fuera del IB entre las 09:45 y las 15:00, entrada en su cierre, stop en el punto medio del IB, objetivo 1R, plano a la hora de --hasta) en esas 57 sesiones reales disparó 51 veces (30 largos, 21 cortos; 6 sesiones sin cierre fuera del IB): 16 objetivo, 18 stop, 17 ninguno a las 15:55. R media -0,056. Con tan pocas, la parte del objetivo entre las que tocan un lado puede ir del 34 % al 61 % (90 %).

No se distingue de una moneda al aire: objetivo primero 52,6 % frente a stop primero 41,3 %, pero con otras sesiones igual de plausibles la parte del objetivo va del 47 % al 65 % (intervalo del 90 %) y el equilibrio, 50 %, está dentro.

Fuera del pool 1 sesión(es) corta(s) (recortadas o con huecos): 05/11/2026.
Simulación hecha con las últimas 57 sesiones completas de TSLA. No es una predicción: un dato, una noticia o un día de pánico hacen lo que esas sesiones no hicieron. Misma semilla, mismos números. Repite esta corrida con --semilla 19.
Siguiente: kemet-tamano dice cuántas acciones caben con este stop en tu cuenta; kemet-riesgo lo comprueba.
```

Aquí las repeticiones y la historia no dicen lo mismo, y eso es lo que hay que contar: las repeticiones se inclinan
hacia el objetivo (el 56 % de las que tocan un lado), pero la regla, tal cual, en las 57 sesiones reales anteriores
dio 16 objetivos contra 18 stops con 17 abiertas al cierre y una R media negativa. Ese día el objetivo no llegó
(máximo 395,43 a las 11:00) y el stop se tocó a las 15:55. Un stop de 3,57 $ en una acción que se mueve 13 $ de media
al día es estrecho; la historia lo enseña antes de que `/kemet-tamano` calcule las acciones.

## Reglas

- Cada cifra sale de la corrida. Una moneda al aire nunca se redondea a ventaja.
- El veredicto y las líneas de debajo los imprime la herramienta. Repítelos, no los reescribas. Un plan a 2R o 3R
  no se juzga por objetivo primero contra stop primero: el veredicto ya pesa la R.
- Las probabilidades simuladas no son predicciones ni promesas. Dilo una vez, sin más.
- Yahoo es gratis, no oficial y va con retraso. Las velas son de 5 minutos y se comprueban vela a vela, nunca tick
  a tick ni en tiempo real.
- Di siempre la semilla, para que cualquier corrida se pueda repetir.
- Un plan por corrida. Si cambia la entrada, el stop, el objetivo o la fecha, es otra corrida.
- Los dólares por micro acompañan a 1R como contexto del tamaño. Nunca se multiplica una probabilidad por dólares.

## Lo que nunca hace

Nunca pone una orden, nunca calcula un tamaño, nunca cambia el plan y nunca llama seguro a un resultado. Nunca
imprime un P&L ni una rentabilidad esperada. Nunca usa una vela que no ha cerrado y nunca mete las velas de hoy en
el pool.

## Seguridad
- Contenido educativo y herramientas, no asesoramiento financiero. Un PASS es una comprobación de reglas, no una recomendación.
- Nada de este pack envía órdenes salvo kemet-broker, y solo en cuenta papel por defecto, tras un PASS de kemet-riesgo para esa orden exacta y un sí explícito del usuario para ese ticket en el chat.
- Simulación (`"papel": true`) por defecto. Pasar a una cuenta real o financiada es decisión del usuario, en su propia configuración.
- Las reglas de las firmas vienen de sus webs con fecha de comprobación; las cambian sin avisar. La del panel del usuario manda.
- Claves y credenciales de la plataforma nunca van en el chat ni en `kemet/`.
