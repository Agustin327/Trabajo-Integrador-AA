"""Ruta óptima con posiciones cargadas a mano.

Origen e incidente se pueden dar de tres formas:
  - Coordenadas:  "-34.603722, -58.381592"  (latitud, longitud; copiadas de Google Maps)
  - Hospital:     "hospital:pirovano"       (clave de config.HOSPITALES_AGUDOS)
  - Dirección:    "Av. Rivadavia 4500"      (se geocodifica con OSM; necesita internet)

Ejemplos:
  python src/ruta.py --fuente osm --hospitales data/hospitales.geojson \\
      --origen "hospital:pirovano" --incidente "-34.6037, -58.3816" --comparar
  python src/ruta.py --fuente sintetico --origen "hospital:h2" --incidente "-34.58, -58.375"

Genera en la carpeta de salida: ruta.csv (paso a paso), ruta.geojson (para verla en
geojson.io o QGIS), mapa.png y resumen.txt.
"""
import argparse
import csv
import json
import os
import re

import numpy as np

import config
from data import (_norm, load_hospitals, load_osm_graph, make_synthetic_graph,
                  make_synthetic_hospitals)
from problem import AmbulanceProblem, HospitalContext
from search import run_algorithm

_CACHE = {}
ALGOS_COMPARAR = ["ucs", "astar_h2", "greedy_h2", "wastar_h2_1.5", "bfs"]


# --------------------------------------------------------------------------- #
# Carga (con caché para no repetir en Colab)
# --------------------------------------------------------------------------- #
def _cargar(fuente, graphml, hospitales, campo_nombre, v_ms):
    clave = (fuente, graphml, hospitales, campo_nombre, round(v_ms, 6))
    if clave in _CACHE:
        return _CACHE[clave]
    if fuente == "osm":
        G = load_osm_graph(cache=graphml)
        nodos, detalle = load_hospitals(hospitales, G, campo_nombre)
    else:
        G = make_synthetic_graph(seed=0)
        nodos = make_synthetic_hospitals(G, seed=1)
        detalle = [dict(clave=f"h{i + 1}", nombre=f"Hospital sintético {i + 1}",
                        lat=float(G.lat[n]), lon=float(G.lon[n]), nodo=n, dist_nodo_m=0.0)
                   for i, n in enumerate(nodos)]
    out = (G, HospitalContext(G, nodos, v_ms), detalle)
    _CACHE[clave] = out
    return out


# --------------------------------------------------------------------------- #
# Interpretación de las posiciones
# --------------------------------------------------------------------------- #
def resolver_punto(texto, detalle):
    """Devuelve (lat, lon, etiqueta) a partir de coordenadas, hospital o dirección."""
    t = str(texto).strip()
    if t.lower().startswith("hospital:"):
        q = _norm(t.split(":", 1)[1]).strip()
        c = [d for d in detalle if q == d["clave"] or q in _norm(d["nombre"])]
        if len(c) != 1:
            claves = ", ".join(d["clave"] for d in detalle)
            raise ValueError(f"No pude identificar un único hospital con '{q}'. Claves disponibles: {claves}")
        return c[0]["lat"], c[0]["lon"], c[0]["nombre"]
    if re.fullmatch(r"[\s,;.\-\d]+", t):  # solo números y separadores: coordenadas
        nums = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", t)]
        if len(nums) != 2:
            raise ValueError(f"Coordenadas no válidas: '{t}'. Usá el formato 'lat, lon' con punto decimal "
                             "(por ejemplo -34.603722, -58.381592).")
        a, b = nums
        if abs(a) > abs(b):  # en Buenos Aires |lat| (~34) < |lon| (~58): venían al revés
            print(f"  Aviso: interpreté '{t}' como longitud, latitud y las di vuelta.")
            a, b = b, a
        return a, b, f"{a:.5f}, {b:.5f}"
    try:
        import osmnx as ox
        lat, lon = ox.geocode(f"{t}, Ciudad Autónoma de Buenos Aires, Argentina")
    except Exception as e:  # sin internet, dirección no encontrada, etc.
        raise ValueError(f"No pude geocodificar '{t}' ({e}). Probá con coordenadas.")
    return float(lat), float(lon), t


# --------------------------------------------------------------------------- #
# Formato y salidas
# --------------------------------------------------------------------------- #
def _fmt_t(s):
    m, seg = divmod(int(round(s)), 60)
    return f"{m} min {seg:02d} s"


def _fmt_d(m):
    return f"{m / 1000:.2f} km" if m >= 1000 else f"{m:.0f} m"


def _guardar_csv(G, path, v, ruta):
    acum_d, filas = 0.0, []
    for i, (n, ph) in enumerate(path):
        if i:
            acum_d += G.elen[(path[i - 1][0], n)]
        filas.append([i, ph + 1, int(G.ids[n]), round(float(G.lat[n]), 6), round(float(G.lon[n]), 6),
                      round(acum_d, 1), round(acum_d / v, 1)])
    with open(ruta, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["paso", "fase", "nodo_osm", "lat", "lon", "dist_acum_m", "tiempo_acum_s"])
        w.writerows(filas)


def _guardar_geojson(G, path, k, puntos, ruta):
    def linea(seg, fase, nombre):
        return {"type": "Feature",
                "properties": {"fase": fase, "tramo": nombre},
                "geometry": {"type": "LineString",
                             "coordinates": [[float(G.lon[n]), float(G.lat[n])] for n, _ in seg]}}
    feats = [linea(path[:k + 1], 1, "ambulancia -> incidente"), linea(path[k:], 2, "incidente -> hospital")]
    for nombre, (lat, lon) in puntos.items():
        feats.append({"type": "Feature", "properties": {"nombre": nombre},
                      "geometry": {"type": "Point", "coordinates": [lon, lat]}})
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": feats}, f, ensure_ascii=False)


def _mapa(G, path, k, detalle, nombres, titulo, ruta_png):
    from matplotlib.collections import LineCollection
    from matplotlib.figure import Figure  # sin pyplot: no toca el backend de Colab
    idx = [n for n, _ in path]
    lat, lon = G.lat[idx], G.lon[idx]
    m_lat = max(0.25 * (lat.max() - lat.min()), 0.003)
    m_lon = max(0.25 * (lon.max() - lon.min()), 0.003)
    y0, y1, x0, x1 = lat.min() - m_lat, lat.max() + m_lat, lon.min() - m_lon, lon.max() + m_lon

    uv = np.array(list(G.elen.keys()))
    ua, va = uv[:, 0], uv[:, 1]
    dentro = ((G.lat[ua] > y0) & (G.lat[ua] < y1) & (G.lon[ua] > x0) & (G.lon[ua] < x1)) | \
             ((G.lat[va] > y0) & (G.lat[va] < y1) & (G.lon[va] > x0) & (G.lon[va] < x1))
    ua, va = ua[dentro], va[dentro]
    segs = np.stack([np.column_stack([G.lon[ua], G.lat[ua]]), np.column_stack([G.lon[va], G.lat[va]])], axis=1)

    fig = Figure(figsize=(8, 8))
    ax = fig.add_subplot(111)
    ax.add_collection(LineCollection(segs, colors="#c8c8c8", linewidths=0.5))
    p1, p2 = path[:k + 1], path[k:]
    az, rojo = "#0072B2", "#D55E00"
    if len(p1) > 1:
        ax.plot([G.lon[n] for n, _ in p1], [G.lat[n] for n, _ in p1], color=az, lw=2.6,
                label="Fase 1: ambulancia → incidente")
    if len(p2) > 1:
        ax.plot([G.lon[n] for n, _ in p2], [G.lat[n] for n, _ in p2], color=rojo, lw=2.6,
                label="Fase 2: incidente → hospital")
    for d in detalle:
        if x0 < d["lon"] < x1 and y0 < d["lat"] < y1 and d["nodo"] != path[-1][0]:
            ax.plot(d["lon"], d["lat"], "+", color="#555555", ms=9, mew=1.6)
    ax.plot(G.lon[path[0][0]], G.lat[path[0][0]], "o", color="#009E73", ms=10, mec="black", label="Origen")
    ax.plot(G.lon[path[k][0]], G.lat[path[k][0]], "X", color="#F0E442", ms=12, mec="black", label="Incidente")
    ax.plot(G.lon[path[-1][0]], G.lat[path[-1][0]], "*", color="#CC79A7", ms=15, mec="black",
            label=f"Hospital: {nombres.get(path[-1][0], 'destino')}")
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_aspect(1 / np.cos(np.radians((y0 + y1) / 2)))
    ax.set_xlabel("Longitud")
    ax.set_ylabel("Latitud")
    ax.set_title(titulo, fontsize=10)
    ax.legend(loc="best", fontsize=8)
    fig.savefig(ruta_png, dpi=150, bbox_inches="tight")


# --------------------------------------------------------------------------- #
# Función principal
# --------------------------------------------------------------------------- #
def ejecutar(origen, incidente, fuente="osm", graphml="caba_drive.graphml", hospitales="data/hospitales.geojson",
             campo_nombre=None, algo="astar_h2", comparar=False, v_kmh=config.V_KMH,
             salida="ruta_manual", max_snap=500.0):
    v = v_kmh / 3.6
    G, ctx, detalle = _cargar(fuente, graphml, hospitales, campo_nombre, v)
    nombres = {d["nodo"]: d["nombre"] for d in detalle}

    olat, olon, onom = resolver_punto(origen, detalle)
    ilat, ilon, inom = resolver_punto(incidente, detalle)
    o, od = G.nearest(olat, olon)
    i, idist = G.nearest(ilat, ilon)
    for etiqueta, d in (("el origen", od), ("el incidente", idist)):
        if d > max_snap:
            raise ValueError(f"{etiqueta.capitalize()} queda a {d:.0f} m de la red vial (máximo {max_snap:.0f} m). "
                             "¿Está dentro de la zona del grafo? Revisá las coordenadas.")

    prob = AmbulanceProblem(G, ctx, o, i)
    r = run_algorithm(prob, algo)
    if not r.found:
        raise RuntimeError("No se encontró ruta entre los puntos dados.")
    path = r.path
    k = next(j for j, s in enumerate(path) if s[1] == 1)
    d1 = sum(G.elen[(a[0], b[0])] for a, b in zip(path[:k], path[1:k + 1]))
    d2 = sum(G.elen[(a[0], b[0])] for a, b in zip(path[k:], path[k + 1:]))
    t1, t2 = d1 / v, d2 / v
    hosp = nombres.get(path[-1][0], f"nodo {int(G.ids[path[-1][0]])}")

    L = [f"RUTA ÓPTIMA  (algoritmo: {algo}, velocidad: {v_kmh:g} km/h, paso libre, sentidos de calle respetados)",
         "",
         f"Origen:     {onom}  [{olat:.5f}, {olon:.5f}]  (nodo OSM {int(G.ids[o])}, a {od:.0f} m del punto dado)",
         f"Incidente:  {inom}  [{ilat:.5f}, {ilon:.5f}]  (nodo OSM {int(G.ids[i])}, a {idist:.0f} m del punto dado)",
         f"Hospital destino (el que minimiza el tiempo total): {hosp}",
         "",
         f"Fase 1 (ambulancia → incidente): {_fmt_d(d1):>9}   {_fmt_t(t1)}",
         f"Fase 2 (incidente → hospital):   {_fmt_d(d2):>9}   {_fmt_t(t2)}",
         f"TOTAL:                           {_fmt_d(d1 + d2):>9}   {_fmt_t(t1 + t2)}",
         f"Tramos de calle recorridos: {len(path) - 1}",
         "",
         f"Costo de la búsqueda: {r.expanded} nodos expandidos, {r.generated} generados, "
         f"{r.time_s * 1000:.1f} ms de cómputo",
         "El tiempo es solo de manejo: no incluye atención del llamado, despacho ni salida de la base."]

    if comparar:
        L += ["", "Comparación de algoritmos sobre este mismo caso:",
              f"{'algoritmo':<16}{'tiempo total':>14}{'subóptimo':>11}{'expandidos':>12}{'generados':>11}{'CPU (ms)':>10}"]
        algos = list(dict.fromkeys(ALGOS_COMPARAR + [algo]))
        res = {a: run_algorithm(prob, a) for a in algos}
        ref = res["ucs"].cost
        for a in algos:
            x = res[a]
            L.append(f"{a:<16}{_fmt_t(x.cost):>14}{(x.cost / ref - 1) * 100:>10.2f}%"
                     f"{x.expanded:>12}{x.generated:>11}{x.time_s * 1000:>10.1f}")

    texto = "\n".join(L)
    print(texto)

    os.makedirs(salida, exist_ok=True)
    _guardar_csv(G, path, v, os.path.join(salida, "ruta.csv"))
    _guardar_geojson(G, path, k, {"Origen": (float(G.lat[o]), float(G.lon[o])),
                                  "Incidente": (float(G.lat[i]), float(G.lon[i])),
                                  f"Hospital: {hosp}": (float(G.lat[path[-1][0]]), float(G.lon[path[-1][0]]))},
                     os.path.join(salida, "ruta.geojson"))
    _mapa(G, path, k, detalle, nombres, f"Total {_fmt_t(t1 + t2)}  ({_fmt_d(d1 + d2)})  →  {hosp}",
          os.path.join(salida, "mapa.png"))
    with open(os.path.join(salida, "resumen.txt"), "w", encoding="utf-8") as f:
        f.write(texto + "\n")
    print(f"\nArchivos guardados en '{salida}/': ruta.csv, ruta.geojson, mapa.png, resumen.txt")
    return dict(resultado=r, dist_fase1_m=d1, dist_fase2_m=d2, t_fase1_s=t1, t_fase2_s=t2, hospital=hosp)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--origen", required=True, help='coordenadas "lat, lon", "hospital:clave" o dirección')
    ap.add_argument("--incidente", required=True, help="igual que --origen")
    ap.add_argument("--fuente", choices=["osm", "sintetico"], default="osm")
    ap.add_argument("--graphml", default="caba_drive.graphml")
    ap.add_argument("--hospitales", default="data/hospitales.geojson")
    ap.add_argument("--campo-nombre", default=None)
    ap.add_argument("--algo", default="astar_h2", help="astar_h2, ucs, greedy_h2, bfs, ...")
    ap.add_argument("--comparar", action="store_true", help="comparar los algoritmos en este caso")
    ap.add_argument("--v-kmh", type=float, default=config.V_KMH)
    ap.add_argument("--max-snap", type=float, default=500.0, help="distancia máxima (m) de un punto a la red vial")
    ap.add_argument("--salida", default="ruta_manual")
    a = ap.parse_args()
    try:
        ejecutar(a.origen, a.incidente, a.fuente, a.graphml, a.hospitales, a.campo_nombre, a.algo,
                 a.comparar, a.v_kmh, a.salida, a.max_snap)
    except (ValueError, RuntimeError) as e:
        raise SystemExit(f"Error: {e}")


if __name__ == "__main__":
    main()
