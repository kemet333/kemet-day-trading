---
name: kemet-plan
description: >-
  Plan de sesión escrito antes de abrir, para futuros intradía (ES, NQ, CL, GC) en cuentas de fondeo y para
  acciones de EE. UU. con la cuenta propia. Junta las franjas de Nueva York con su hora en Madrid, las
  ventanas sin operar (alrededor de cada dato de la agenda, la apertura 09:30 a 09:45 y los minutos antes de
  estar plano), el semáforo del día, los niveles de ayer y de la noche, el tamaño por operación con la regla
  Kemet y la hora límite de la firma. Con una acción, el tamaño va en acciones enteras con el stop en dólares
  por acción, sin hora límite ni niveles de la noche. También guarda la agenda de datos del día, a mano o
  desde el calendario gratuito de Forex Factory. Úsala cuando el usuario diga «hazme el plan de hoy», «qué
  datos salen hoy», «a qué hora no opero», «cuántos contratos hoy con stop de 40», «cuántas acciones de TSLA
  con stop de 3 dólares», «apunta que a las 8:30 sale el IPC», o antes de la apertura, después de
  kemet-niveles y antes de kemet-entrada y kemet-riesgo.
argument-hint: "plan [--mercado NQ|TSLA] [--stop PTS] [--semaforo verde|ambar|rojo] [--escribir] | agenda --fecha AAAA-MM-DD --dato \"08:30 IPC fuerte\""
---

# kemet-plan

Un plan de sesión es una hoja escrita antes de que abra el mercado: a qué horas no toco nada, qué niveles tengo
marcados, cuántos contratos caben con mi stop en mi límite de hoy y a qué hora tengo que estar plano. Este tool la
escribe con la plantilla de `kemet-desk/references/plan-de-sesion.md`, con cifras y horas, para que al usuario le
quede una sola cosa que hacer a continuación. No dice hacia dónde irá el precio.
La mayoría de los que hacen day trading pierde dinero, y una herramienta no cambia eso.

`${CLAUDE_SKILL_DIR}` es la carpeta de esta skill (donde está este SKILL.md).

```bash
python3 "${CLAUDE_SKILL_DIR}/plan.py" plan                               # el mercado de kemet/config.json (NQ si no hay)
python3 "${CLAUDE_SKILL_DIR}/plan.py" plan --stop 40 --escribir          # con el tamaño en contratos y guarda kemet/plan-sesion.json
python3 "${CLAUDE_SKILL_DIR}/plan.py" plan --mercado CL --semaforo rojo  # fuerza el semáforo
python3 "${CLAUDE_SKILL_DIR}/plan.py" plan --stop 6 --mercado ES --drawdown 2000 --diario 1000   # sin config: tus límites
python3 "${CLAUDE_SKILL_DIR}/plan.py" plan --mercado TSLA --stop 3.57 --escribir   # una acción con la cuenta propia (stop en $ por acción)
python3 "${CLAUDE_SKILL_DIR}/plan.py" agenda --fecha 2026-11-11 --dato "08:30 IPC fuerte" --dato "10:30 Inventarios EIA CL"
python3 "${CLAUDE_SKILL_DIR}/plan.py" agenda --fecha 2026-11-13         # un día sin datos también se apunta
python3 "${CLAUDE_SKILL_DIR}/plan.py" agenda --auto                      # los datos USD de hoy del calendario de Forex Factory
python3 "${CLAUDE_SKILL_DIR}/plan.py" agenda --auto --fecha 2026-11-13 --dato "10:30 Inventarios EIA CL"   # y añade los tuyos
```

Flags de `plan`: `--mercado`, `--stop PTS` (tu stop en puntos del contrato), `--drawdown` y `--diario` (dólares, solo
sin config), `--semaforo`, `--sin-niveles` (no consulta Yahoo), `--escribir`, `--json`, `--ahora "AAAA-MM-DD HH:MM"`
en hora de Nueva York, `--offline RUTA` (JSON de Yahoo guardado para los niveles). Cada `--dato` de `agenda` es
`"HH:MM nombre [fuerte] [ES NQ CL GC]"`: la hora de Nueva York, el nombre, `fuerte` si mueve la sesión entera y, si
solo afecta a un contrato, su código. `agenda --auto` admite `--mercado` (deja fuera los datos que solo afectan a otro
contrato) y `--offline RUTA` (un `ff_calendar_thisweek.json` guardado). `KEMET_DIR` cambia la carpeta `kemet/`. Código
de salida 0 si hay plan, 1 si `--auto` no pudo bajar el calendario, 2 si hay un error (una línea, sin traza).

## Qué lee y escribe

| archivo | qué |
| --- | --- |
| `kemet/config.json` | opcional, lo escribe `tamano.py config`: `mercado`, `drawdown`, `limite_diario_firma`, `max_micro`, `fallos_y_paras`, `semaforo`, `sin_entradas_antes`, `sin_entradas_despues`, `plano_a`, `hora_limite` y su zona, `zona_usuario`, `cuenta_nombre`. Con `tipo_cuenta: "propia"` (`tamano.py config --propia`): `perdida_max_dia`, `riesgo_por_operacion`, `presupuesto`, `max_posicion_pct`, `max_orden_usd`, `efectivo_pct`. Sin él: NQ, verde, 09:45 a 14:00, plano a las 15:55, Madrid, y sin bloque de tamaño |
| `kemet/agenda.json` | los datos del día: `{"fecha", "datos": [{"hora", "nombre", "fuerte", "mercados"}]}`. La escribe `plan.py agenda` (a mano o con `--auto`) o el usuario; ejemplo en `agenda.example.json`. Si falta o es de otro día, el plan avisa |
| Forex Factory, `nfs.faireconomy.media/ff_calendar_thisweek.json` | solo con `agenda --auto`: el calendario de la semana en curso, gratis y sin clave, una sola petición. Se quedan los datos USD de impacto alto (fuerte) y medio (no fuerte); los de impacto bajo y los festivos no abren ventana |
| `kemet/niveles.json` | si es de hoy y del mismo mercado, los niveles salen de ahí; si no, de Yahoo (5 días de velas de 5 minutos) |
| Yahoo, gráfico v8 | solo para los niveles, gratis y sin clave; con `--sin-niveles` no se toca |
| `kemet/plan-sesion.json` | con `plan --escribir`: `generado`, `mercado`, `fecha`, `semaforo`, `razones`, `ventanas`, `niveles`, `tamano`, `hora_limite`, `hora_limite_ny`, `plano_a`, `siguiente`. kemet-riesgo y kemet-diario leen las ventanas de la agenda |

## Las reglas

- **Franjas (índices)**: preapertura 08:00 a 09:30, apertura 09:30 a 09:45, mejor franja 09:45 a 11:30, hora de comer
  11:30 a 13:30, tarde 13:30 a 15:30, cierre 15:30 a 16:00, todas en hora de Nueva York. CL tiene su pit de 09:00 a
  14:30 y los inventarios de la EIA los miércoles a las 10:30; GC de 08:20 a 13:30. Si `zona_usuario` es
  `Europe/Madrid`, cada hora lleva al lado la de Madrid calculada con la fecha (5, 6 o 7 horas según la semana del
  año). Con otra zona deja solo Nueva York y lo dice.
- **Ventanas en las que no se opera**: 10 minutos antes y después de cada dato de la agenda; 20 si lleva `fuerte`
  (IPC, NFP, FOMC, PCE, PIB, PPI, ISM, ventas minoristas, peticiones cuando el mercado mira el empleo). Un dato con
  `mercados` solo abre ventana en esos contratos (la EIA en CL). Siempre la apertura 09:30 a 09:45 para quien empieza
  y los 5 minutos antes de `plano_a`. Dentro de la ventana no se abre, no se mantiene y no se dejan órdenes pendientes.
- **Agenda automática**: `--auto` traduce los nombres habituales (CPI → IPC, Non-Farm Employment Change → nóminas
  no agrícolas, Unemployment Claims → peticiones de desempleo, FOMC, PPI, PCE, GDP → PIB, Retail Sales → ventas
  minoristas, ISM, Crude Oil Inventories → inventarios EIA con `mercados: ["CL"]`) y deja el resto tal cual. Dos datos
  a la misma hora van en una sola ventana («IPC subyacente y IPC»). La hora sale del desfase del propio dato. Si la red
  falla, una línea, código 1 y la agenda que hubiera sigue valiendo. El calendario es de terceros: comprueba la hora
  de los datos que te importan.
- **Semáforo**: el de `config.json` (verde si no hay). Pasa a ámbar solo cuando la agenda tiene un dato fuerte para
  ese mercado, y lo dice en las razones. `--semaforo` lo fuerza (VIX alto, gamma negativa, una semana que se mueve
  mucho más de lo normal: eso lo juzga el usuario, el tool no lo mide). Rojo imprime además la regla: quien empieza,
  mira.
- **Tamaño (la regla Kemet, la misma de `tamano.py`)**: pérdida máxima del día = la menor entre el límite diario de la
  firma (si lo hay) y un cuarto del drawdown; en ámbar o rojo, la mitad. Riesgo por operación = esa cifra entre
  `fallos_y_paras` (3). Contratos = parte entera de riesgo por operación / (stop en puntos × valor del punto del
  micro), con el tope de micros de la cuenta. Cero contratos es un rechazo, no un tamaño pequeño. Sin `--stop` imprime
  la pérdida del día y el riesgo por operación y pide el stop. Sin config y con `--stop` hacen falta `--drawdown` (y
  `--diario` si la firma lo tiene); sin ninguno de los dos no hay bloque de tamaño y lo dice.
- **Hora límite**: la de la firma en su zona (`America/Chicago` en Topstep, una hora menos que Nueva York) convertida
  a Nueva York, y `plano_a`, que tiene que ir antes; si no va antes, avisa.
- **Cuenta propia y acciones**: con `tipo_cuenta: "propia"` la pérdida máxima del día y el riesgo por operación son
  los del config (la mitad en ámbar o rojo) y no hay hora límite de firma. Con un ticker (`--mercado TSLA`) el stop va
  en dólares por acción y el tamaño en acciones enteras: riesgo por operación / stop; con el cierre de ayer como
  precio de referencia se aplican además los topes de posición (`max_posicion_pct` del presupuesto), orden máxima y
  efectivo (presupuesto menos el colchón), y se dice cuál manda; kemet-tamano los recalcula con la entrada real. Los
  niveles son máximo, mínimo y cierre de ayer, la apertura de 15 minutos y el día (una acción no tiene noche); si no
  llegan, avisa y pide marcarlos a mano. Las ventanas son las de la agenda (un dato con `mercados` solo para futuros
  no cuenta) y la apertura 09:30 a 09:45. Un futuro con la cuenta propia da micros con el tope `max_micro` si lo hay.
  Una acción con una cuenta de firma sale sin bloque de tamaño y lo dice.
- **Lo único que hago a continuación**: una frase según la hora: antes de las 08:00, en preapertura, dentro de una
  ventana (dice cuál y hasta cuándo), en horario de entradas, después de `sin_entradas_despues`, después de `plano_a`,
  con la sesión cerrada o en fin de semana.

## Pasos

1. Antes de abrir, si no hay `kemet/agenda.json`, ejecuta `plan.py agenda --auto` y enséñale al usuario lo que ha
   bajado; si falla o falta algo, pregunta hora, nombre y si es fuerte y escríbelo con `--dato`. Un día sin datos
   también se apunta, para que el plan no avise.
2. Pide el stop habitual en puntos si el usuario no lo ha dicho. Sin él, el plan sale sin contratos.
3. Ejecuta `plan.py plan --stop X --escribir`. Enséñale el plan tal cual: ventanas con horas en su zona, niveles,
   tamaño con la regla que lo limita y la hora límite.
4. Si el usuario describe una regla de su firma distinta de la del config, dile que las firmas las cambian, que
   confirme en su panel, y usa la suya.
5. Cierra con la frase de «lo único que hago a continuación». Después, `/kemet-entrada` para seguir la ruptura del
   balance inicial vela a vela y `/kemet-riesgo` antes de cada orden; al terminar el día, `/kemet-diario`.
6. Los sistemas que Kemet Capital opera con agentes en cuentas de fondeo llevan filtros y parámetros validados en su
   propio banco; no están en este pack. kemet-capital.com

## Ejemplo: NQ, miércoles 11 de noviembre de 2026

Config de ejemplo: Apex 50K EOD PA (drawdown 2.500 $, sin límite diario, 10 micros, hora límite 16:59 de Nueva York,
plano a las 15:55, usuario en Madrid). El 11 de noviembre de 2026 fue festivo bancario en EE. UU. y el calendario
real no trae datos (con `--auto` lo dice: «festivo bancario: en el calendario, sin ventana»), así que el ejemplo usa
la agenda típica de `agenda.example.json`, escrita a mano:

```
python3 plan.py agenda --fecha 2026-11-11 --dato "08:30 IPC fuerte" --dato "10:00 ISM servicios" --dato "10:30 Inventarios EIA CL" --dato "14:00 Subasta del Tesoro a 10 años"
Agenda del 2026-11-11:
  08:30  IPC · fuerte (ventana de 20 min)
  10:00  ISM servicios (ventana de 10 min)
  10:30  Inventarios EIA (ventana de 10 min) · solo CL
  14:00  Subasta del Tesoro a 10 años (ventana de 10 min)
Guardado kemet/agenda.json
```

Después el plan, a las 08:00 de Nueva York con un stop de 40 puntos, sobre el fixture real del pack:

```
python3 plan.py plan --stop 40 --ahora "2026-11-11 08:00" --offline tests/fixtures/yahoo --escribir
PLAN · NQ · mié 2026-11-11 · 14:00 Madrid / 08:00 NY
Cuenta: Apex 50K EOD · PA
Semáforo: ámbar porque hay un dato fuerte en la sesión: IPC a las 08:30
Hoy no se opera en:
  08:10–08:50 NY (14:10–14:50 Madrid)        IPC a las 08:30, dato fuerte
  09:30–09:45 NY (15:30–15:45 Madrid)        apertura: quien empieza espera
  09:50–10:10 NY (15:50–16:10 Madrid)        ISM servicios a las 10:00
  13:50–14:10 NY (19:50–20:10 Madrid)        Subasta del Tesoro a 10 años a las 14:00
  15:50–15:55 NY (21:50–21:55 Madrid)        últimos minutos antes de estar plano
  Dentro de la ventana no se abre, no se mantiene y no se dejan órdenes pendientes.
Entradas nuevas solo entre 09:45 NY (15:45 Madrid) y 14:00 NY (20:00 Madrid).
Niveles que marco (sesión anterior 2026-11-10, velas de 5 min de Yahoo):
  Ayer       máximo 28.090   mínimo 27.516   cierre 27.835,25
  Noche      máximo 28.397,50   mínimo 27.847,75
  Gamma: el pivote y los muros de calls y puts los marcas tú desde tu fuente de opciones; este pack no los tiene.
Mi tamaño: 1 MNQ por operación con stop de 40 pts
  pérdida máxima del día 312 $ (un cuarto del drawdown = 625 $, la mitad por ámbar)
  riesgo por operación 104 $ (entre 3 fallos y paras) · al stop pierdes 80,00 $ por MNQ
Hora límite de mi firma: 16:59 NY (22:59 Madrid) · plano a las 15:55 NY (21:55 Madrid)
Franjas del día (NY / Madrid):
  Preapertura    08:00–09:30 / 14:00–15:30    marca niveles, revisa la agenda, decide el tamaño; el dato de las 08:30 no se opera
  Apertura       09:30–09:45 / 15:30–15:45    quien empieza, espera; quien no, tamaño reducido y stop amplio
  Mejor franja   09:45–11:30 / 15:45–17:30    se forma el balance inicial; aquí van las operaciones del plan
  Hora de comer  11:30–13:30 / 17:30–19:30    rango y falsas rupturas: tamaño mínimo o nada; revisión de media sesión
  Tarde          13:30–15:30 / 19:30–21:30    vuelve el volumen; a las 14:00 hay datos (FOMC, Tesoro)
  Cierre         15:30–16:00 / 21:30–22:00    reposicionamiento; plano antes de la hora límite, sin aperturas nuevas
Antes de cada operación: sé dónde va mi stop y lo pongo en la plataforma; opero como mucho los contratos que caben; he escrito por qué entro y qué me haría salir; si llego a mi pérdida máxima del día, cierro la plataforma.
Lo único que hago a continuación: pon el stop y el tamaño por escrito, marca los niveles en la plataforma y no entres antes de las 09:45 NY.
Guardado kemet/plan-sesion.json
```

Con el calendario real de esa semana (`tests/fixtures/kemet-plan/ff_calendar_thisweek.json`), el martes 10 sale así:

```
python3 plan.py agenda --auto --fecha 2026-11-10 --offline tests/fixtures/kemet-plan/ff_calendar_thisweek.json
Agenda del 2026-11-10:
  04:00  FOMC Member Waller Speaks (ventana de 10 min)
  08:30  IPC subyacente y IPC · fuerte (ventana de 20 min)
  Fuente: tests/fixtures/kemet-plan/ff_calendar_thisweek.json. Impacto alto = fuerte, medio = no fuerte, bajo fuera. Comprueba la hora de los datos que te importan.
Guardado kemet/agenda.json
```

La EIA de las 10:30 no abre ventana porque el plan es de NQ; con `--mercado CL` aparece 10:20 a 10:40. Sin el IPC
el semáforo sería verde, la pérdida máxima del día 625 $, el riesgo por operación 208 $ y cabrían 2 MNQ con el mismo
stop (208 / 80 = 2,6, parte entera 2). Con un stop de 2 puntos cabrían 52 y el tope de la cuenta lo deja en 10. A las
10:35 el bloque de niveles añade la apertura (28.254,25 a 28.426) y el balance inicial (28.199 a 28.426), y la frase
final pasa a «operaciones del plan hasta las 14:00 NY, cada una con el stop puesto en la plataforma antes de entrar».
Sin `kemet/agenda.json` el plan sale con un aviso y solo dos ventanas: la apertura y los minutos antes de estar plano.

## Ejemplo: TSLA, miércoles 11 de noviembre de 2026, cuenta propia

Cuenta propia de 5.000 $, 50 $ por operación y 150 $ al día (`tamano.py config --propia --mercado TSLA`), a las 08:00
de Nueva York sin agenda, sobre el fixture real del pack. El stop, 3,57 $ por acción, es el de la ruptura del rango de
15 minutos de ese día (rango 386,35 a 392,67; entrada 393,08 a las 10:15 con el stop en el punto medio 389,51):

```
python3 plan.py plan --stop 3.57 --ahora "2026-11-11 08:00" --offline tests/fixtures/yahoo --escribir
PLAN · TSLA · mié 2026-11-11 · 14:00 Madrid / 08:00 NY
Cuenta: Cuenta propia · 5.000 $
Aviso: no hay kemet/agenda.json: no conozco los datos de hoy (escríbela con `plan.py agenda`)
Semáforo: verde porque sin agenda del día, doy por hecho que no hay datos fuertes
Hoy no se opera en:
  09:30–09:45 NY (15:30–15:45 Madrid)        apertura: quien empieza espera
  15:50–15:55 NY (21:50–21:55 Madrid)        últimos minutos antes de estar plano
  Dentro de la ventana no se abre, no se mantiene y no se dejan órdenes pendientes.
Entradas nuevas solo entre 09:45 NY (15:45 Madrid) y 15:00 NY (21:00 Madrid).
Niveles que marco (sesión anterior 2026-11-10, velas de 5 min de Yahoo):
  Ayer       máximo 380   mínimo 370,43   cierre 379,80
  Sin sesión nocturna: una acción abre a las 09:30 y los primeros 15 minutos son su balance inicial.
Mi tamaño: 9 acciones de TSLA por operación con stop de 3,57 $ por acción (manda posición máxima)
  pérdida máxima del día 150 $ (tu pérdida máxima del día) · riesgo por operación 50,00 $ · al stop pierdes 3,57 $ por acción
  riesgo por operación   50,00 $ / 3,57 $ por acción                        14 acciones
  posición máxima        75 % de 5.000 $ = 3.750 $ / 379,80 $                9 acciones  <- manda
  orden máxima           4.000 $ / 379,80 $                                 10 acciones
  efectivo               5.000 $ menos 500 $ de colchón = 4.500 $ / 379,80 $   11 acciones
  posición, orden máxima y efectivo con el cierre de ayer (379,80 $) como precio; con la entrada real los recalcula kemet-tamano
Hora límite: ninguna, es tu cuenta · plano a las 15:55 NY (21:55 Madrid)
Franjas del día (NY / Madrid):
  …las seis franjas de los índices, que son las de la NYSE…
Lo único que hago a continuación: pon el stop y el tamaño por escrito, marca los niveles en la plataforma y no entres antes de las 09:45 NY.
Guardado kemet/plan-sesion.json
```

Con la agenda del IPC a las 08:30 (dato fuerte) el semáforo pasa a ámbar, la pérdida del día a 75 $, el riesgo por
operación a 25 $ y caben 7 acciones (ahí manda el riesgo); la EIA de las 10:30 no abre ventana porque es solo de CL. A
las 10:35 los niveles añaden la apertura (386,35 a 392,67) y no hay bloque de una hora: en una acción el balance
inicial son esos 15 minutos. Con `--sin-niveles` no hay precio de referencia y el tamaño sale solo por el riesgo (14).

## Reglas

- La agenda la escribe el usuario (o tú desde lo que te diga): el tool no sabe qué datos salen hoy y lo avisa.
- El semáforo del tool solo ve la agenda. Volatilidad, gamma o estrés los pone el usuario con `--semaforo`.
- Las horas de las ventanas se dicen siempre en la zona del usuario y en la de Nueva York.
- El tamaño sin stop no es un tamaño. Si falta el stop, pídelo antes de hablar de contratos.
- Una regla del panel de la firma vence al config y al plan.

## Lo que nunca hace

No da dirección, ni entradas, ni objetivos de precio; no mide la volatilidad ni el estrés de mercado; no manda órdenes;
no promete que respetar el plan dé dinero.

## Seguridad
- Contenido educativo y herramientas, no asesoramiento financiero. Un PASS es una comprobación de reglas, no una recomendación.
- Nada de este pack envía órdenes salvo kemet-broker, y solo en cuenta papel por defecto, tras un PASS de kemet-riesgo para esa orden exacta y un sí explícito del usuario para ese ticket en el chat.
- Simulación (`"papel": true`) por defecto. Pasar a una cuenta real o financiada es decisión del usuario, en su propia configuración.
- Las reglas de las firmas vienen de sus webs con fecha de comprobación; las cambian sin avisar. La del panel del usuario manda.
- Claves y credenciales de la plataforma nunca van en el chat ni en `kemet/`.
