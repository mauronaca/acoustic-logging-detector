# SPEC: banco de pruebas de energía del nodo

## Contexto

Nodo acústico de detección de motosierras (TIF FIUBA). Este banco valida el bloque de energía: estimar el estado de carga (SoC) de la batería y registrar curvas de carga y descarga en función del aporte solar. Los datos se consultan por HTTP GET desde la red local.

Dos entregables: esquemático en KiCad (vía MCP) y firmware PlatformIO.

## Hardware disponible

1. ESP32-S3 DevKitC-1 sobre placa de borneras.
2. DFRobot Solar Power Manager 5V (DFR0559): entrada solar, entrada de batería, salida 5 V.
3. Un módulo INA219 (shunt 0,1 Ω, dirección 0x40).
4. Celda 18650 UltraFire en portapilas. Capacidad rotulada 6800 mAh, no confiable; la capacidad real se mide en este banco.
5. Panel solar DFRobot 5 V / 5 W.
6. Divisor resistivo 200k / 100k para la tensión del panel.

## Conexionado

1. INA219 en serie con el positivo de la batería, lado alto: VIN+ a BAT+ del DFR0559, VIN− al positivo de la celda. Negativo de la celda directo a BAT− del DFR0559.
2. Convención de signo resultante: corriente positiva = carga, negativa = descarga. La tensión de bus del INA219 es la tensión del borne de la celda.
3. Panel conectado directo a SOLAR IN del DFR0559. Divisor 200k (arriba) / 100k (abajo) desde SOLAR IN+ a GND, punto medio a GPIO4 (ADC1). Relación 3:1; con 6,5 V en circuito abierto el ADC ve 2,2 V.
4. I2C: SDA GPIO8, SCL GPIO9, VCC 3V3 y GND del ESP32.
5. Salida 5 V del DFR0559 al pin 5V del DevKitC. GND común único en el DFR0559.

## Esquemático (KiCad)

1. Diseño modular: una hoja jerárquica por módulo (panel, DFR0559, batería + INA219, ESP32-S3). Cada módulo comercial se representa con un símbolo propio que expone solo sus borneras y headers, con la serigrafía real de la placa como nombre de pin.
2. Nombres de red: VPANEL, VPANEL_ADC, VBAT_CHG (lado DFR0559 del shunt), VBAT (lado celda), 5V, 3V3, GND, SDA, SCL.
3. Divisor del panel como resistencias discretas en la hoja del ESP32 o en una hoja propia.
4. Dejar prevista una segunda posición de INA219 entre panel y SOLAR IN (dirección 0x41, puente A0), marcada como no montada (DNP).
5. Anotar en el esquemático la convención de signo de corriente de batería.
6. Correr ERC sin errores antes de dar por cerrado.
7. Entregar dos esquemáticos en `hardware/`: `01_cableado.kicad_sch` (módulos como cajas, con las conexiones dibujadas como líneas) y `02_conceptual.kicad_sch` (cada módulo reemplazado por su circuito equivalente). Al cerrar cada uno, imprimir el PDF (`kicad-cli sch export pdf` o `export_schematic_pdf`) y guardarlo en `hardware/` junto al esquemático (`01_cableado.pdf`, `02_conceptual.pdf`). Reexportar los dos PDF cada vez que cambie un esquemático.

## Firmware

Base: PlatformIO, framework Arduino, board `esp32-s3-devkitc-1`, librería `adafruit/Adafruit INA219`. Credenciales WiFi en `src/secrets.h`, no versionado.

### Mediciones por muestra (cada 10 s)

1. `v_bat` (V) e `i_bat_ma` (mA, con signo) del INA219.
2. `v_panel` (V) del ADC, promedio de 16 lecturas con `analogReadMilliVolts`, multiplicado por 3.
3. `mah_net`: integración de `i_bat_ma` en el tiempo.
4. `i_load_ma`: consumo del nodo visto desde la batería. Se autocalibra de noche: con estado `noche`, `i_load_ma` se actualiza como media móvil de `-i_bat_ma`. Valor inicial configurable.
5. `i_charge_est_ma` = `i_bat_ma + i_load_ma`: corriente que entrega el cargador. Es una estimación de la potencia solar útil, sin pérdidas del cargador.
6. `soc_cc` (%): conteo de carga sobre `CAPACIDAD_MAH`.
7. `soc_ocv` (%): estimación por tensión con tabla OCV de Li-ion. Se reporta en paralelo como referencia, no corrige `soc_cc` salvo en el reset de 100 %.
8. `estado`: uno de `cargando`, `descargando`, `carga_completa`, `noche`.

### Reglas

1. Reset de 100 %: `v_bat >= 4.15` y `0 <= i_bat_ma < 50` sostenido 60 s. Pone `soc_cc = 100` y registra el evento.
2. `noche`: `v_panel < 1.0`.
3. `carga_completa`: reset de 100 % vigente y `v_panel` mayor a `UMBRAL_VOC` (panel en circuito abierto).
4. `cargando` / `descargando`: por signo de `i_bat_ma` con banda muerta de ±5 mA.
5. Persistir `soc_cc`, `mah_net` e `i_load_ma` en NVS (`Preferences`) cada 5 minutos para sobrevivir reinicios.
6. Timestamp por NTP en UTC-3; si no hay hora, segundos desde arranque.

### Constantes configurables (arriba de `main.cpp`)

`PIN_SDA`, `PIN_SCL`, `PIN_VPANEL_ADC`, `VPANEL_DIV_RATIO`, `SAMPLE_PERIOD_MS`, `HISTORY_LEN`, `CAPACIDAD_MAH` (default 1500 hasta medirla), `I_LOAD_INICIAL_MA`, `UMBRAL_VOC`.

### Historia

Buffer circular en RAM de 2880 muestras (8 h a 10 s).

### API HTTP

1. `GET /api/now`: muestra instantánea en JSON.
2. `GET /api/history`: historia completa en JSON, enviada en streaming sin armar un String gigante.
3. `GET /api/history.csv`: misma historia en CSV con encabezado.
4. `POST /api/reset_soc?valor=N`: fija `soc_cc` manualmente para arrancar una prueba.

Campos: `t, v_bat, i_bat_ma, v_panel, i_load_ma, i_charge_est_ma, mah_net, soc_cc, soc_ocv, estado`.

## Procedimiento de prueba

1. Carga completa con USB hasta el reset de 100 %.
2. Descarga sin panel hasta el corte del DFR0559. `mah_net` al corte es la capacidad real de la celda; actualizar `CAPACIDAD_MAH`.
3. Ciclo de 24 a 48 h con panel al aire libre. Exportar CSV y graficar `v_bat`, `i_bat_ma`, `soc_cc` y `i_charge_est_ma` contra el tiempo, y `i_charge_est_ma` contra `v_panel`.

## Criterios de aceptación

1. Compila con `pio run` sin warnings nuevos.
2. Los tres GET responden desde un navegador de la red local.
3. El signo de `i_bat_ma` coincide con la convención: positivo con USB conectado, negativo sin fuentes.
4. `soc_cc` y `soc_ocv` difieren menos de 15 puntos con la celda en reposo después del paso 2 del procedimiento.
5. Un reinicio del ESP32 conserva `soc_cc` y `mah_net`.

## Fuera de alcance

Deep sleep, MQTT, captura de audio y PCB propia. Este banco corre siempre despierto con WiFi activo.

## Laboratorio

KiCad y el MCP corren en una VM (VirtualBox + Vagrant), separada del Windows. Claude Code corre en el Windows y usa el MCP de la VM por SSH. La VM no necesita Claude Code ni login.

Archivos: `Vagrantfile`, `vagrant/provision.sh` (root: escritorio, KiCad, Node, Claude Code) y `vagrant/provision-user.sh` (usuario: clona, compila y registra el MCP dentro de la VM).

### Levantar la VM

```powershell
vagrant up                                   # primer arranque lento: baja la box y los paquetes
vagrant provision --provision-with usuario   # repetir solo el paso del MCP si falla npm
vagrant halt                                 # apagar
vagrant snapshot restore kicad10-listo       # volver al estado limpio
```

- Box `bento/ubuntu-24.04`, escritorio XFCE con autologin del usuario `vagrant`, 4 GB de RAM y 2 CPU.
- KiCad **10** por el PPA oficial (`ppa:kicad/kicad-10.0-releases`). El MCP (kicad-mcp 2.8.x) escribe los esquemáticos en formato KiCad 10 y KiCad 9 no los abre (`kicad-cli sch erc` falla con "Failed to load schematic"). Otra versión: `$env:KICAD_VERSION="9.0"` antes de `vagrant up`.
- Con el hipervisor de Windows activo (WSL2, Docker, Hyper-V) VirtualBox corre sobre NEM y necesita estos ajustes, ya incluidos en el `Vagrantfile`: `--paravirt-provider none` (sin esto el kernel se cuelga al arrancar), ratón tableta USB y teclado USB (el PS/2 emulado pierde clicks y teclas), aceleración 3D apagada y `boot_timeout` de 900 s.
- Requisitos del host: VirtualBox 7.x y Vagrant 2.4.x.

### Archivos y portapapeles

La carpeta del proyecto (la del `Vagrantfile`) está compartida en `/home/vagrant/proyecto` y el portapapeles es bidireccional. Es una decisión explícita: el MCP puede leer y escribir en esa carpeta, que incluye `.git` y `.vagrant/` (clave SSH de la VM), así que parte del aislamiento se pierde.

### Conectar el MCP desde Windows

La VM tiene que estar encendida. Claude Code lanza el MCP dentro de la VM a través de SSH, con la clave que genera Vagrant (`vagrant ssh-config` muestra la ruta, el puerto 2222 y el usuario). Desde la raíz del repo:

```powershell
$k = ("$PWD\.vagrant\machines\default\virtualbox\private_key") -replace '\\','/'
claude mcp add kicad -s user -- ssh -T -o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL -o IdentitiesOnly=yes -o LogLevel=ERROR -i $k -p 2222 vagrant@127.0.0.1 "PYTHONPATH=/usr/lib/python3/dist-packages node /home/vagrant/KiCAD-MCP-Server/dist/index.js"
claude mcp list                              # kicad debe figurar como Connected
```

- Si `claude` no está en el PATH (extensión de VS Code), usar `%USERPROFILE%\.vscode\extensions\anthropic.claude-code-<versión>-win32-x64\resources\native-binary\claude.exe`.
- Las herramientas del MCP aparecen al reiniciar la sesión de Claude Code.
- No hace falta Node, Python ni KiCad en Windows: todo eso corre en la VM. Windows solo necesita el cliente `ssh` (viene con Windows 11).
- El `PYTHONPATH` es el del módulo `pcbnew` del paquete apt de KiCad.

### Problemas conocidos

- Aviso de Vagrant por guest additions 7.0.16 contra VirtualBox 7.2: no afecta al MCP ni a la carpeta compartida.
- Si aparece la pantalla de login en vez del escritorio: el usuario debe estar en el grupo `autologin` y `50-autologin.conf` debe fijar `autologin-session=xfce` (ya lo hace `provision.sh`). El servidor gráfico tarda unos 2 minutos en levantar.
- La red NAT de la VM a veces corta: el aprovisionamiento ya reintenta `add-apt-repository` y `npm install`.

El costo es mantener una VM más. A cambio, KiCad y el MCP quedan fuera del Windows, y Claude Code solo ejecuta en la VM el comando del MCP.
