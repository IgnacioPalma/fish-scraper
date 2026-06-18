# IFOP `Cód. Barco` ↔ `COD_BARCO`: la fórmula y cómo se descubrió

**Resultado principal — fórmula exacta y determinista:**

```
COD_BARCO   = HEX(id_interno_ifop + 5)      # hexadecimal en MAYÚSCULAS
id_interno  = int(COD_BARCO, 16) − 5
```

El `COD_BARCO` "anonimizado" que aparece en `bitacora_full.csv` / `bitacora.csv`
y en `backup.csv` (ej. `E6774`, `C35E3`, `DBBCE`) **no es un hash**: es el
"Cód. Barco" decimal interno de IFOP **más un desplazamiento constante de 5,
escrito en hexadecimal**. Conociendo uno se obtiene el otro con una sola línea.

```python
def cod_barco_desde_ifop(id_interno: int) -> str:
    return format(id_interno + 5, "X")

def ifop_desde_cod_barco(cod: str) -> int:
    return int(cod, 16) - 5
```

---

## De dónde sale cada identificador

| Identificador | Fuente | Ejemplo | Formato |
|---|---|---|---|
| **Nombre embarcación** | SIEM Electrónico IFOP (HTML), columna "Cód. Barco" | `ROCIO V` | texto |
| **`id_interno_ifop`** | misma columna, parte numérica antes del `-` | `950324` | decimal 6 díg. |
| **`COD_BARCO`** | `bitacora_full.csv` / `backup.csv` | `E8039` | hex 5 car. |

En el SIEM la columna "Cód. Barco" trae `"<id_interno> - <NOMBRE>"`
(ej. `950324 - ROCIO V`). Ese `id_interno` decimal es el que IFOP llama
oficialmente "Cód. Barco" en su instructivo de bitácora; el `COD_BARCO`
hexadecimal de las bases de datos es ese mismo número desplazado en +5.

---

## Cómo se descubrió (registro reproducible)

La fórmula **no** se conocía de antemano. Se llegó a ella así:

1. **Puente temporal.** El SIEM da `nombre + id_interno + fecha_recalada +
   puerto`, pero no el `COD_BARCO`. Se emparejó cada recalada IFOP en Caldera
   con las recaladas de Caldera de `bitacora_full.csv` y `backup.csv` que
   tuvieran la **misma marca temporal al minuto** (ver
   `processing/bitacora/match_ifop_names.py`), y por **voto de consenso** por
   embarcación se asignó un `COD_BARCO`. Esto produjo 22 pares
   `id_interno ↔ COD_BARCO` de alta/media confianza.

2. **Inspección numérica.** Al convertir cada `COD_BARCO` de hexadecimal a
   decimal y restar el `id_interno`, la diferencia resultó **constante = 5**
   en 21 de los 22 pares:

   | Embarcación | id_interno | COD_BARCO | int(hex) | diferencia |
   |---|---|---|---|---|
   | DANIELA ANDREA | 943983 | E6774 | 943988 | **5** |
   | SEA QUEST | 800222 | C35E3 | 800227 | **5** |
   | DON ATILIO | 942708 | E6279 | 942713 | **5** |
   | … (21 pares) | … | … | … | **5** |
   | EL PATO | 943778 | E5B98 | 940952 | −2826 ⚠ |

3. **Validación cruzada gratis.** El único par que **no** cumplía (EL PATO)
   era exactamente la fila que el emparejamiento temporal ya había marcado
   como **colisión** (`E5B98` pertenece en realidad a DON BENITO II, que sí
   cumple +5). Es decir, la fórmula detecta de forma independiente el falso
   positivo del emparejamiento temporal. Evidencia fuerte de que el +5 es real
   y no una coincidencia.

4. **Recuperación de faltantes.** Aplicando la fórmula a las 25 embarcaciones
   sin emparejamiento temporal, 7 producen un `COD_BARCO` que **ya existe** en
   `bitacora_full.csv`/`backup.csv` (CHUBASCO I, FORTUNA II, FRANCISCA,
   ANTONIA, DON MARCIAL, RAQUEL I, SION) — barcos que el cruce temporal había
   perdido. Las otras 18 dan códigos válidos que simplemente no están en
   nuestros datos (en su mayoría viajes 2025–2026 posteriores al alcance de la
   bitácora).

---

## Implicancia: el cruce temporal ya no es necesario

El emparejamiento espacio-temporal (`match_ifop_names.py`) sirvió para
**descubrir** la regla. Una vez conocida, `COD_BARCO` se calcula directamente
desde el `id_interno` IFOP para **cualquier** embarcación: sin ventana
temporal, sin colisiones, sin techo de cobertura. Los votos temporales quedan
como verificación opcional.

El recorrido completo de identificadores queda cerrado:

```
nombre embarcación ── id_interno IFOP ──(+5, hex)── COD_BARCO ──(bitácora/backup)── recaladas, capturas
            └── (Res. 02358/2025, registro Sernapesca) ── RPA
```

## Salvedad pendiente de verificar

El desplazamiento `+5` se confirmó en 22 pares, todos de la **flota de Caldera**
en bandas de `id_interno` ~900k–950k (más FORTUNA II=100132 y DON MARCIAL=
709013, que también cumplen). Antes de confiar ciegamente en `+5` como
constante global, conviene confirmar que no sea específico de banda usando
embarcaciones de otros rangos de `id_interno`. La evidencia disponible apunta a
constante global, pero la muestra está dominada por una sola flota.

---

## El registro como ficha central

`processing/registry/enrich_register_ifop.py` aplica la fórmula para añadir
`IFOP_ID` y `COD_BARCO` a `data/processing/registry/register_clean.csv`, cruzando por
nombre contra el SIEM. Así el registro enlaza `Nº RPA ↔ nombre ↔ IFOP_ID ↔
COD_BARCO` en una sola tabla. Notas del cruce:

- **Cobertura**: solo embarcaciones cuyo nombre aparece en el SIEM (42 de 204
  en la corrida actual). De esos `COD_BARCO`, 30 ya existen en
  `bitacora_full.csv`/`backup.csv` — confirmación independiente de la fórmula.
- **Homónimos**: el registro histórico reinscribe nombres (ej. tres
  "FORTUNA I"). El IFOP_ID es de un solo casco, así que se asigna a la
  inscripción más reciente; los homónimos antiguos quedan en blanco.
- La enriquecimiento, al derivar `COD_BARCO` desde el IFOP_ID propio de cada
  barco, corrige el único falso positivo del cruce temporal (EL PATO, ver
  arriba): le asigna su código real `E66A7` en vez del vecino `E5B98`.

## Archivos relacionados

- `processing/bitacora/match_ifop_names.py` — parseo SIEM + cruce temporal que
  originó los pares de validación.
- `processing/registry/enrich_register_ifop.py` — aplica la fórmula al registro.
- `data/processing/registry/register_clean.csv` — ficha central
  `Nº RPA ↔ nombre ↔ IFOP_ID ↔ COD_BARCO`.
- `data/bitacora/ifop_cod_barco_lookup.csv` — tabla
  `nombre ↔ id_interno ↔ COD_BARCO` con confianza.
- `data/bitacora/ifop_siem/` — exportaciones HTML del SIEM Electrónico IFOP.
- `data/bitacora/cod_barco_lookup_leads.md` — registro de la búsqueda
  (esta fórmula la cierra).
