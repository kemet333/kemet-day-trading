# Kemet Day Trading

*English version: [README.en.md](README.en.md).*

Dieciséis skills que convierten a Claude en tu equipo de trading: escanea miles de gráficos, vigila noticias y
filings, lee resultados, sigue las operaciones del Congreso, marca los niveles de la sesión, escribe el plan, vigila
la ruptura del rango vela a vela, pone el stop y el objetivo antes de entrar, repite el resto del día 10.000 veces
antes de arriesgar nada, calcula el tamaño y el riesgo con tus reglas, manda la orden a un bróker en papel solo
con tu sí, avisa, revisa el diario y decide qué cuenta de fondeo comprar.

Acciones de EE. UU. y futuros (ES, NQ, YM, RTY, CL, GC, SI, HG, NG, 6E, ZN, ZB). Gratis, MIT, sin registro, sin
clave de API. Las herramientas son Python estándar que lee datos públicos gratuitos (velas de Yahoo Finance, los
listados de Nasdaq Trader, EDGAR de la SEC, el House Clerk) y las reglas publicadas de Topstep, Apex, Tradeify,
Alpha Futures y Lucid, con fecha de comprobación.

Nada de este pack envía órdenes salvo kemet-broker, y solo en cuenta papel por defecto, tras un PASS de
kemet-riesgo para esa orden exacta y un sí explícito tuyo para ese ticket. La regla de entrada que trae es la
didáctica, sin filtro: la máquina del tiempo enseña lo que habría hecho antes, y muchas veces es un coin flip. La
mayoría de los que hacen day trading pierde dinero, y una herramienta no cambia eso.

Hecho por [Kemet Capital](https://kemet-capital.com). Los sistemas que Kemet opera con agentes en cuentas de
fondeo llevan filtros y parámetros validados en su propio banco; no están en este pack: esto es el equipo, abierto.
La arquitectura sigue la de [The Day Trader skill](https://github.com/Jakeschincariol/day-trader-skill)
de Jake Schincariol (MIT): todo lo que hace aquel está aquí, en español, más futuros, prop firms, plan, diario y
geometría de riesgo.

## Instalar

Pega esto en Claude:

```
https://github.com/kemet333/kemet-day-trading

instala la skill
```

Como plugin, en Claude Code:

```
/plugin marketplace add kemet333/kemet-day-trading
/plugin install kemet-day-trading@kemet-day-trading
```

Claude Code pone el nombre del plugin delante (`/kemet-day-trading:kemet-entrada`). Si prefieres
`/kemet-entrada` a secas, copia las carpetas:

```bash
git clone https://github.com/kemet333/kemet-day-trading.git
cp -r kemet-day-trading/kemet-* ~/.claude/skills/
```

Para un solo proyecto, las mismas carpetas en `.claude/skills/` de tu repo. En Claude.ai o la app de Claude:
descarga el zip de [kemet-capital.com/skill](https://www.kemet-capital.com/skill/) y súbelo en Ajustes, Capacidades,
Skills: es el pack entero como una sola skill. Sin Claude Code ni skills, pega cualquier `SKILL.md` al principio
de un chat y funciona como método; pierdes las herramientas de Python, no las reglas.

Hace falta Python 3.8 o más nuevo. Nada que instalar con pip. Funciona en Mac, Linux y Windows.

## Las dieciséis

| comando | qué es | qué hace |
| --- | --- | --- |
| `/kemet-desk` | El desk | Te sitúa (mercado, cuenta, stop, horario), elige la pieza y las encadena en orden. |
| `/kemet-scanner` | Scanner | Barre miles de acciones (universo de Nasdaq Trader) antes de abrir y a las 10:15, con cierres diarios y el rango de apertura, y los doce futuros con su balance inicial y el máximo y mínimo de ayer. |
| `/kemet-noticias` | Noticias | Titulares y filings 8-K por ticker con hora y etiqueta, y la agenda macro del día, en un solo sitio. |
| `/kemet-niveles` | Niveles | Máximo, mínimo y cierre de ayer, rango nocturno, apertura y balance inicial, y dónde está el precio. |
| `/kemet-plan` | Plan de sesión | El plan escrito: franjas, ventanas de datos en las que no se opera, semáforo, niveles, tamaño, hora límite de tu firma. |
| `/kemet-entrada` | Entrada | La ruptura del balance inicial vela a vela: formando, esperando, disparado o caducado. |
| `/kemet-salida` | Salida | Stop y objetivo antes de entrar, al tick, en puntos y en dólares por micro. |
| `/kemet-maquina` | Máquina del tiempo | Repite el resto de la sesión 10.000 veces con las velas del propio contrato y repasa la historia real de la regla. |
| `/kemet-tamano` | Tamaño | Tu cuenta (una firma de fondeo o tu propio presupuesto) y cuántos micros o acciones caben con tu stop en tu límite del día. |
| `/kemet-riesgo` | Riesgo | PASS o BLOCK por orden: stop, pérdida, límite del día, tres fallos y paras, ventanas, hora límite, Globex. |
| `/kemet-alertas` | Alertas | Stop, objetivo, plano a, la hora límite de tu firma y el reloj de Globex, cada una suena una vez. |
| `/kemet-diario` | Diario | Revisión del CSV de operaciones: cumplimiento del plan antes que resultado, tres bien, dos mal, una corrección. |
| `/kemet-broker` | Bróker | Convierte la orden con PASS en un ticket en palabras llanas; con tu sí, Claude la manda a Alpaca en papel. Futuros, a mano en tu plataforma. |
| `/kemet-resultados` | Resultados | Lee los XBRL de la SEC: trimestres, ingresos, beneficio, BPA, márgenes y cuándo toca el próximo informe. |
| `/kemet-congreso` | Congreso | Las declaraciones de operaciones de los congresistas (STOCK Act), el día que se publican. Un gancho, no una estrategia. |
| `/kemet-geometria` | Geometría | Qué cuenta de fondeo comprar, cuánto arriesgar y cuándo retirar, con el estudio de 76 cuentas. |

## Cómo se usa

Todo cae en una carpeta `kemet/` de tu proyecto y cada skill lee lo que escribió la anterior:

```
scanner -> noticias -> niveles -> plan                          (antes de abrir)
entrada -> salida -> maquina -> tamano -> riesgo -> broker      (una operación)
alertas                                                         (mientras está abierta)
riesgo registrar -> diario                                      (después)
noticias / resultados / congreso                                (cuando toque)
```

Un ejemplo con datos reales: NQ, miércoles 11 de noviembre de 2026. (Con una acción el camino es el mismo: el
scanner la encuentra, la entrada vigila su rango de apertura de 15 minutos, el tamaño sale en acciones enteras
contra tu presupuesto y el bróker la manda en papel con tu sí. TSLA ese mismo día está en los SKILL.md.)

1. **`/kemet-tamano`**, una vez: `tamano.py config --firma apex --cuenta eod-pa-150 --mercado NQ` escribe
   tu cuenta con sus reglas y la regla Kemet del día (un cuarto del drawdown; la mitad en ámbar).
2. **`/kemet-niveles`** antes de abrir: máximo, mínimo y cierre del martes, el rango de la noche, y a las
   10:30 el balance inicial: 28.199 a 28.426, 227 puntos.
3. **`/kemet-plan`**: las ventanas del día (la apertura de 09:30 a 09:45 y los datos que le des), el semáforo,
   los niveles y el tamaño que cabe con tu stop.
4. **`/kemet-entrada`** vigila la ruptura desde las 10:30: la primera vela de 5 minutos que cierra por encima
   del balance inicial, o por debajo, dispara; una mecha no. Ese día la vela de 10:40 cerró en 28.429,75, por
   encima del alto: disparado largo a las 10:45 (barra 15). Sin entradas nuevas después de las 15:00.
5. **`/kemet-salida`**: stop en el punto medio del balance inicial, 28.312,50, objetivo a 1R, 28.547, plano a
   las 15:55. Riesgo 117,25 puntos: 234,50 dólares por MNQ.
6. **`/kemet-maquina`** repite el resto de la sesión 10.000 veces con las velas de 5 minutos de NQ de las 46
   sesiones anteriores (semilla 19, repetible): objetivo primero 45,5 %, stop primero 46,3 %, ninguno 8,2 %, R
   media −0,007. La misma regla en esas 46 sesiones reales disparó 39 veces: 14 objetivo, 13 stop, 12 ninguno.
   Veredicto: casi una moneda al aire. Eso es lo que hay que saber antes de poner nada.
7. **`/kemet-tamano`**: con la regla Kemet, en una Apex 50K (166,67 dólares por operación) no cabe ni un micro
   con ese stop, y lo dice sin escribir una orden más pequeña; en una Apex 150K cabe 1 MNQ.
8. **`/kemet-riesgo`** comprueba la orden contra tu firma y tu día: PASS o BLOCK con el motivo. A las 10:45 el
   MNQ de la 150K pasa; dos micros a las 09:40 se bloquean por pérdida, ventana de apertura y horario. Si pasa,
   la pones tú en tu plataforma y la registras.
9. **`/kemet-alertas`**: el stop, el objetivo, el plano a y la hora límite de tu firma.
10. **`/kemet-diario`** al acabar la semana, con tu CSV.

Las cifras exactas de ese día, con la salida real de cada herramienta, están en el `SKILL.md` de cada skill.

## Las herramientas

Todo Python estándar. Leen endpoints públicos y son educadas con ellos (una petición cada medio segundo, un
reintento en un 429). `--ahora "2026-11-11 10:35"` fija el reloj en hora de Nueva York y repite un día;
`--offline ARCHIVO` lee velas guardadas; `--json` da el documento entero; `--escribir` guarda en `kemet/`.

```bash
python3 kemet-scanner/scanner.py universo                              # -> kemet/universo.txt (unas 5.900 acciones)
python3 kemet-scanner/scanner.py diario                                # antes de abrir -> kemet/watchlist.json
python3 kemet-scanner/scanner.py orb --a 10:15                         # rupturas del rango de apertura
python3 kemet-scanner/scanner.py futuros                               # los doce contratos
python3 kemet-noticias/noticias.py --tickers TSLA --horas 12           # titulares, 8-K y la agenda macro
python3 kemet-niveles/niveles.py --mercado NQ --escribir             # -> kemet/niveles.json
python3 kemet-plan/plan.py agenda --dato "08:30 IPC fuerte"            # -> kemet/agenda.json
python3 kemet-plan/plan.py plan --stop 18 --escribir                   # -> kemet/plan-sesion.json
python3 kemet-entrada/entrada.py check --escribir                      # -> kemet/entrada.json
python3 kemet-entrada/entrada.py watch --hasta 15:00                   # vela a vela hasta el disparo
python3 kemet-salida/salida.py plan --escribir                         # -> kemet/plan.json
python3 kemet-maquina/maquina.py run --escribir                        # 10.000 repeticiones + la historia
python3 kemet-tamano/tamano.py config --firma apex --cuenta eod-pa-150 # -> kemet/config.json (cuenta de firma)
python3 kemet-tamano/tamano.py config --propia --presupuesto 5000 --max-perdida-operacion 50 --max-perdida-dia 150
python3 kemet-tamano/tamano.py calc --stop 18                          # cuántos micros caben
python3 kemet-tamano/tamano.py orden --escribir                        # -> kemet/orden.json
python3 kemet-riesgo/riesgo.py check                                   # PASS / BLOCK por orden
python3 kemet-broker/broker.py mostrar                                 # el ticket, LISTO solo con PASS de hoy
python3 kemet-broker/broker.py registrar --huella H --id-broker ID --precio P
python3 kemet-riesgo/riesgo.py registrar --resultado -120              # apunta el resultado
python3 kemet-resultados/resultados.py AAPL --trimestres 8             # trimestres, márgenes, BPA
python3 kemet-congreso/congreso.py recientes --dias 45 --miembro pelosi
python3 kemet-alertas/alertas.py add --desde-plan                      # stop, objetivo, plano a
python3 kemet-alertas/alertas.py check                                 # suena lo que tocó, una vez
python3 kemet-diario/diario.py revisar operaciones.csv                 # la revisión
```

```bash
python3 -m unittest discover -s tests -v
```

Los tests van sin red, sobre datos reales guardados (velas de Yahoo de NQ, ES y TSLA de 5 minutos, 60 días hasta
el 12 de noviembre de 2026; CL, GC y AAPL, 5 días; la pared de 234 gráficos del 19 de octubre, los listados de
Nasdaq Trader, los XBRL de Apple y Coca-Cola y los PTR del House Clerk del pack de referencia) y reproducen las
cifras de los ejemplos.

## Letra pequeña

**No es asesoramiento financiero.** Es software que lee datos públicos y hace aritmética. No conoce tu
situación y no ve el futuro. La mayoría de los que hacen day trading pierde dinero. Puedes perder dinero, y
pagar evaluaciones que no apruebes. Decide tú y, si necesitas consejo, busca a un profesional con licencia.

**Ninguna orden sin tu sí.** Solo `/kemet-broker` puede llevar a una orden, y solo después de que `/kemet-riesgo`
pase esa orden exacta y tú escribas sí para ese ticket en el chat. Pon la herramienta del bróker en «Necesita
aprobación» en Claude, nunca en «Permitir siempre», para que la tarjeta de Claude sea un segundo control. Cuenta
papel por defecto (`"papel": true`); las claves van en el archivo de configuración del conector (su bloque `env`), nunca en el chat. En futuros no hay
conector gratuito: la operación la pones tú en tu plataforma. Kemet Capital opera con agentes, en su plataforma,
sistemas con filtros y parámetros validados en su propio banco; eso es otro producto y no está aquí.

**Las operaciones del Congreso son públicas, no información privilegiada.** Los congresistas declaran sus
operaciones de más de 1.000 dólares hasta 45 días después (STOCK Act). `/kemet-congreso` lee esas declaraciones.

**La máquina del tiempo es una simulación, no una predicción.** Se construye con las velas de 5 minutos del
propio contrato en las sesiones anteriores (Yahoo guarda unas 48). El futuro hace cosas que esas sesiones no
hicieron: un dato, un gap, un titular. Trata sus probabilidades como una comprobación de realidad, nunca como
una promesa.

**Un stop es un plan, no una garantía.** En un mercado rápido o en un gap una orden stop se llena lejos de su
precio. La pérdida máxima que se muestra es la del precio del stop.

**Los datos son gratuitos y no oficiales.** El endpoint de gráficos de Yahoo no es una API oficial: los
futuros llegan con unos 10 minutos de retraso, puede fallar o limitarte. Las velas son de 5 minutos, nunca tick a
tick. EDGAR y el House Clerk piden que te identifiques (`sec_user_agent` en `kemet/config.json`). Comprueba en tu
plataforma cualquier cifra que importe antes de actuar.

**Las reglas de las firmas cambian.** Vienen de sus webs con fecha de comprobación; la de tu panel manda.
Confírmalas antes de pagar y antes de cada retiro.

**La ruptura del balance inicial no es un sistema con ventaja.** Es la regla didáctica más conocida del day
trading, sin filtro: sirve para aprender a ejecutar con stop, tamaño y hora de salida escritos de antemano, y para
ver en la máquina del tiempo lo que habría hecho en las sesiones anteriores. Nadie promete que gane; a menudo no lo hace.

## Archivos

```
kemet-desk/        SKILL.md, references/ (plan de sesión, revisión)
kemet-scanner/     SKILL.md, scanner.py
kemet-noticias/    SKILL.md, noticias.py
kemet-niveles/     SKILL.md, niveles.py
kemet-plan/        SKILL.md, plan.py, agenda.example.json
kemet-entrada/     SKILL.md, entrada.py
kemet-salida/      SKILL.md, salida.py
kemet-maquina/     SKILL.md, maquina.py
kemet-tamano/      SKILL.md, tamano.py, reglas-de-firmas.json, reglas-de-firmas.md, config.example.json
kemet-riesgo/      SKILL.md, riesgo.py
kemet-alertas/     SKILL.md, alertas.py, alertas.example.json
kemet-broker/      SKILL.md, broker.py, claude_desktop_config.example.json
kemet-diario/      SKILL.md, diario.py, diario.example.csv
kemet-resultados/  SKILL.md, resultados.py, metricas.example.json
kemet-congreso/    SKILL.md, congreso.py
kemet-geometria/   SKILL.md, geometria-de-riesgo.md
tests/             unittest + fixtures reales de Yahoo
```

Cada carpeta con herramienta lleva su copia de `comun.py` (horas de Nueva York y Madrid sin zoneinfo, velas de
Yahoo, el día de negociación de CME, contratos y micros, acciones por su ticker, los relojes de Globex y de la
NYSE, los archivos de `kemet/`), para que cada skill se instale sola.

MIT. Hecho por [Kemet Capital](https://kemet-capital.com).
