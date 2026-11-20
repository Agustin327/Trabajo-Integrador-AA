# Datos

## hospitales.geojson (debe estar en esta carpeta)

Hospitales de la Ciudad de Buenos Aires, del portal de datos abiertos del Gobierno de la Ciudad:
https://data.buenosaires.gob.ar/dataset/hospitales

Descargá el recurso en formato GeoJSON, guardalo como `data/hospitales.geojson` y subilo al repositorio.
De ese archivo el programa se queda solo con los 14 hospitales generales de agudos (ver `src/config.py`).

## Red vial

Se descarga automáticamente de OpenStreetMap con OSMnx la primera vez que se ejecuta
(se guarda como `caba_drive.graphml`, que no se versiona).
Datos © colaboradores de OpenStreetMap, licencia ODbL: https://www.openstreetmap.org/copyright
