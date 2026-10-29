# Banco de pruebas de energía — módulo solar

Cada módulo se alimenta con un panel solar que carga una celda 18650 y genera 5 V para un ESP32-S3. El ESP32 mide el estado energético del sistema.

## Hardware

| Módulo | Función |
|---|---|
| Panel DFRobot 5 V / 5 W | Fuente de energía (máx. ~1 A) |
| DFR0559 Solar Power Manager 5V | Carga la celda y genera los 5 V |
| Celda 18650 | Almacenamiento |
| INA219 (0x40) | Mide tensión y corriente de la celda |
| ESP32-S3 DevKitC | Carga del sistema y adquisición de datos |
| Divisor 200k/100k + 100 nF | Mide la tensión del panel en GPIO4 |

## Flujo de energía

```
Panel ──► PMOS ──► CN3065 ──► nodo BAT ──► MT3608 ──► SY6280 ──► ESP32-S3 (5V)
 │      anti-inv.  cargador       │         boost 5V   límite 1,1 A
 │                 lineal         │
 │                              shunt 0,1Ω (INA219)
 └─► divisor 1/3 ─► GPIO4         │
                                 Celda 18650 ── DW06D (protección)
```

Todo, salvo el INA219, el divisor y el ESP32, está **dentro del DFR0559**:

- **PMOS anti-inversión**: protege contra el panel conectado al revés. Pierde ~20 mV.
- **CN3065**: cargador lineal en dos etapas. Su eficiencia es aproximadamente V_BAT / V_panel (~74 %) y no hace MPPT.
  - **CC (corriente constante)**: entrega I_SET = 1800 / RISET = 900 mA.
  - **CV (tensión constante)**: mantiene 4,2 V; la corriente de la celda cae sola a medida que se llena.
- **DW06D**: protege la celda. Corta por sobrecarga (4,3 V), sobredescarga (2,4 V) y sobrecorriente (3 A).
- **MT3608 + SY6280**: elevan la tensión de la celda a 5,1 V y limitan la salida a 1,1 A.

## Corrientes en el nodo BAT

El cargador, la celda y el boost comparten el mismo nodo:

```
I_BAT (cargador) = I_celda + I_boost
```

El INA219 mide **solo I_celda**:

- **Positiva**: la celda se carga.
- **Negativa**: la celda entrega.

| Situación | I_BAT | I_celda (INA219) |
|---|---|---|
| Sol, carga CC | 900 mA | + (900 − I_boost) |
| Sol, celda casi llena (CV) | ≈ I_boost | + pequeña → 0 |
| Sol débil | < I_boost | − (la celda completa) |
| Noche | 0 | − I_boost |

> Con el ESP32 encendido, el CN3065 nunca marca DONE, porque el consumo del boost mantiene la corriente de su pin por encima del umbral de fin de carga.

## Qué mide el ESP32

### Medidas directas

| Métrica | Fuente |
|---|---|
| V_panel | GPIO4 × 3 |
| V_celda | INA219 (tensión de bus) |
| I_celda | INA219 (shunt) |
| P_celda | INA219 (V × I) |

### Métricas derivadas

- **Estado**:
  - cargando: I > 0
  - llena: V ≈ 4,2 V con I chica
  - descargando: I < 0
  - noche: V_panel ≈ 0
- **Energía cargada y descargada por día** (mAh / Wh), integrando I_celda en el tiempo.
- **Balance diario**: si lo cargado de día supera lo consumido de noche, el sistema es sostenible.
- **Estado de carga (%)**: por conteo de carga, recalibrado cuando la celda está llena.
- **Autonomía estimada**: mAh restantes ÷ corriente de descarga.
- **Horas de sol útiles**: el tiempo con V_panel por encima de un umbral.
- **Consumo del sistema (de noche)**: I_boost = −I_celda. Es la corriente del lado de la batería e incluye el ESP32 y las pérdidas del boost.
- **Eficiencia del cargador**: η ≈ V_celda / V_panel.
- **Potencia estimada del panel**: P_panel ≈ V_panel × (I_celda + I_boost medido de noche).
- **Capacidad real de la celda**: con una descarga completa, para seguir su degradación.

### Lo que no se mide

- La corriente y la potencia reales del panel; solo se pueden estimar.
- El consumo del ESP32 durante el día, porque se mezcla con la carga.
- La eficiencia del panel, porque no se mide la irradiancia.
- La eficiencia del boost.

**Para medirlas** alcanza con un segundo INA219 (0x41) entre el panel y el DFR0559, o un tercero en la línea de 5 V del ESP32.