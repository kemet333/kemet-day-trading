# Plan de sesión

La sesión que importa para ES, NQ, CL y GC es la de Nueva York. Todas las horas abajo van en hora de Nueva York; conviértelas a la del usuario (Madrid va 6 horas por delante casi todo el año; en las semanas de cambio de hora pueden ser 5 o 7: calcula con la fecha, no de memoria).

## Franjas del día (índices ES y NQ)

| Franja | Hora NY | Qué hace el precio | Qué hace el trader |
|---|---|---|---|
| Preapertura | 08:00–09:30 | Poco volumen; los datos de las 08:30 lo mueven de golpe | Marca niveles, revisa la agenda, decide el tamaño. No se opera el dato |
| Apertura | 09:30–09:45 | Los quince minutos más bruscos del día | Quien empieza, espera. Quien no, tamaño reducido y stop amplio |
| Mejor franja | 09:45–11:30 | Se forma el balance inicial; los movimientos tienen continuidad | Aquí van las operaciones del plan |
| Hora de comer | 11:30–13:30 | Rango y falsas rupturas | Tamaño mínimo o nada. Buen momento para la revisión de media sesión |
| Tarde | 13:30–15:30 | Vuelve el volumen; a las 14:00 hay datos (FOMC, Tesoro) | Operaciones del plan, con la ventana de las 14:00 respetada |
| Cierre | 15:30–16:00 | Reposicionamiento, movimientos sin lógica intradía | Plano antes de la hora límite de la firma. Sin aperturas nuevas |

CL tiene su sesión de pit de 09:00 a 14:30 y los inventarios de la EIA los miércoles a las 10:30. GC de 08:20 a 13:30. Fuera de esas horas el precio existe, pero el volumen no.

## Ventanas en las que no se opera

- 10 minutos antes y 10 después de un dato fuerte en la divisa del contrato. 20 minutos en los que mueven la sesión entera: CPI, NFP, FOMC y rueda de prensa, PCE, PIB, PPI, peticiones de desempleo cuando el mercado está pendiente del empleo, ISM, ventas minoristas.
- Dentro de la ventana no se abre, no se mantiene y no se dejan órdenes pendientes. Varias firmas lo tienen escrito; las que no, lo penalizan igual con el deslizamiento.
- Primer movimiento tras el dato: el más brusco y el menos fiable. Se deja pasar.

## Niveles que se marcan antes de abrir

Niveles, no predicciones. Se marcan en el gráfico y se usan para saber dónde está el precio respecto a lo que ya pasó.

1. Sesión regular anterior: máximo, mínimo y cierre (liquidación).
2. Sesión nocturna: máximo y mínimo desde las 18:00 NY.
3. Apertura: máximo y mínimo de los primeros 15 minutos; balance inicial: los de la primera hora.
4. En ES y NQ, los niveles de gamma de las opciones del índice: el pivote (flip) y los muros de calls y puts. Por debajo del pivote el precio se amplía y hacen falta stops con más aire y menos contratos; por encima tiende a frenarse y volver, y funcionan mejor los rangos que las rupturas.
5. Perfil de volumen de la sesión anterior: POC, VAH y VAL. Los POC que el precio no ha vuelto a tocar (naked) son imanes conocidos; se marcan.

## Semáforo del día

Antes de decidir el tamaño se mira el contexto y se reduce cuando se acumulan señales:

- Verde: sin datos fuertes, volatilidad y estrés normales. Tamaño habitual. Un día tranquilo no es excusa para subir contratos.
- Ámbar: un dato fuerte en la sesión, VIX alto, gamma negativa, una semana que se mueve bastante más de lo normal, un estrecho marítimo cortado. Tamaño a tres cuartos con una señal, a la mitad con dos o más.
- Rojo: estrés de mercado muy alto o volatilidad extrema. Quien empieza, mira; quien no, la mitad del tamaño y nunca dentro de la ventana del dato.
- Cerrado: fin de semana. Se revisa el diario, se marcan máximo, mínimo y cierre del viernes y se mira qué datos salen el lunes.

## Checklist antes de cada operación

1. Sé dónde va mi stop y lo pongo en la plataforma.
2. Opero como mucho los contratos que caben con mi stop en mi límite de hoy.
3. He escrito por qué entro y qué me haría salir.
4. Si llego a mi pérdida máxima del día, cierro la plataforma.

## Plantilla de plan

```
PLAN · {mercado} · {fecha} · {hora Madrid} / {hora NY}
Semáforo: {verde|ámbar|rojo} porque {razones}
Hoy no se opera en: {ventanas con horas}
Niveles que marco: {PDH} {PDL} {PDC} · {ONH} {ONL} · {OR} · {gamma si ES/NQ}
Mi tamaño: {n} {micro} por operación con stop de {x} pts · pérdida máxima del día {usd}
Hora límite de mi firma: {hh:mm} · plano antes
Lo único que hago a continuación: {una frase}
```
