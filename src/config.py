"""Parámetros fijados del problema (ver README.md)."""

# Velocidad promedio de la ambulancia con paso libre.
# Fuente: Rehn et al. (2017), Emergency Medicine Journal: mediana de 46,1 km/h
# en respuesta de emergencia en Londres. Es un supuesto, no una medición local.
V_KMH = 46.0
V_MS = V_KMH / 3.6

# Semilla para generar los incidentes al azar (reproducibilidad).
SEED = 42

PLACE = "Ciudad Autónoma de Buenos Aires, Argentina"

# Radio terrestre usado por OSMnx; así la distancia en línea recta (haversine)
# es consistente con las longitudes de arista del grafo.
EARTH_RADIUS_M = 6371009.0

# Los 14 hospitales generales de agudos del GCBA (guardia 24 h, 365 días).
# Clave = fragmento del nombre, en minúsculas y sin tildes, para filtrar el GeoJSON.
HOSPITALES_AGUDOS = {
    "alvarez": "Hospital General de Agudos Dr. T. Álvarez",
    "argerich": "Hospital General de Agudos Dr. C. Argerich",
    "durand": "Hospital General de Agudos Dr. C. Durand",
    "fernandez": "Hospital General de Agudos Dr. J. A. Fernández",
    "grierson": "Hospital General de Agudos Dra. Cecilia Grierson",
    "penna": "Hospital General de Agudos J. M. Penna",
    "pinero": "Hospital General de Agudos P. Piñero",
    "pirovano": "Hospital General de Agudos Dr. I. Pirovano",
    "ramos mejia": "Hospital General de Agudos J. M. Ramos Mejía",
    "rivadavia": "Hospital General de Agudos B. Rivadavia",
    "santojanni": "Hospital General de Agudos Donación F. Santojanni",
    "tornu": "Hospital General de Agudos Dr. E. Tornú",
    "velez sarsfield": "Hospital General de Agudos D. Vélez Sarsfield",
    "zubizarreta": "Hospital General de Agudos A. Zubizarreta",
}

# Categorías de casos según la distancia por calle de la fase 1 (metros).
UMBRAL_CORTO_M = 3000.0   # corto: hasta 3 km
UMBRAL_LARGO_M = 8000.0   # medio: 3 a 8 km; largo: más de 8 km
