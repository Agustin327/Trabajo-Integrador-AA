"""Carga de datos: grafo vial (OpenStreetMap) y hospitales (GeoJSON del GCBA).

El grafo se maneja con índices enteros 0..N-1 para que la búsqueda sea rápida.
"""
import json
import os
import unicodedata

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree

import config


# --------------------------------------------------------------------------- #
# Geometría
# --------------------------------------------------------------------------- #
def haversine_vec(lat1, lon1, lat2, lon2):
    """Distancia en metros sobre la esfera (acepta arrays y escalares)."""
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dphi = p2 - p1
    dlam = np.radians(lon2) - np.radians(lon1)
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dlam / 2) ** 2
    return 2 * config.EARTH_RADIUS_M * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def manhattan_vec(lat1, lon1, lat2, lon2):
    """Distancia Manhattan en metros (ejes latitud/longitud). Puede sobreestimar."""
    lat_m = np.radians((np.asarray(lat1) + lat2) / 2)
    m_lat = 111195.0
    return np.abs(np.asarray(lat1) - lat2) * m_lat + np.abs(np.asarray(lon1) - lon2) * m_lat * np.cos(lat_m)


# --------------------------------------------------------------------------- #
# Grafo vial
# --------------------------------------------------------------------------- #
class RoadGraph:
    """Grafo dirigido: adj[u] = [(v, longitud_m), ...]. Respeta los sentidos de calle."""

    def __init__(self, ids, lat, lon, us, vs, ls):
        self.ids = np.asarray(ids)
        self.lat = np.asarray(lat, dtype=float)
        self.lon = np.asarray(lon, dtype=float)
        self.n = len(self.ids)
        self.adj = [[] for _ in range(self.n)]
        self.elen = {}
        for u, v, l in zip(us.tolist(), vs.tolist(), ls.tolist()):
            self.adj[u].append((v, l))
            self.elen[(u, v)] = l
        self.n_edges = len(self.elen)
        self.csr = csr_matrix((ls, (us, vs)), shape=(self.n, self.n))
        self._kx = 111320.0 * np.cos(np.radians(float(np.mean(self.lat))))
        self._tree = None

    def haversine_to(self, lat, lon):
        return haversine_vec(self.lat, self.lon, lat, lon)

    def _xy(self, lat, lon):
        return np.column_stack([np.asarray(lon, dtype=float) * self._kx,
                                np.asarray(lat, dtype=float) * 110574.0])

    def nearest(self, lat, lon):
        """Índice del nodo más cercano y distancia aproximada en metros."""
        if self._tree is None:
            self._tree = cKDTree(self._xy(self.lat, self.lon))
        d, i = self._tree.query(self._xy([lat], [lon]))
        return int(i[0]), float(d[0])


def build_road_graph(ids, lat, lon, edge_list):
    """Arma el RoadGraph: quita lazos y aristas paralelas (deja la más corta)
    y se queda con la mayor componente fuertemente conexa, para que todo par
    de nodos tenga camino dirigido."""
    ids = np.asarray(ids)
    lat = np.asarray(lat, dtype=float)
    lon = np.asarray(lon, dtype=float)
    n = len(ids)
    best = {}
    for u, v, l in edge_list:
        if u == v:
            continue
        l = max(float(l), 0.01)  # evita aristas de longitud 0
        k = (u, v)
        if k not in best or l < best[k]:
            best[k] = l
    us = np.fromiter((k[0] for k in best), dtype=np.int64, count=len(best))
    vs = np.fromiter((k[1] for k in best), dtype=np.int64, count=len(best))
    ls = np.fromiter(best.values(), dtype=float, count=len(best))
    m = csr_matrix((ls, (us, vs)), shape=(n, n))
    _, lab = connected_components(m, directed=True, connection="strong")
    keep = np.flatnonzero(lab == np.argmax(np.bincount(lab)))
    new = -np.ones(n, dtype=np.int64)
    new[keep] = np.arange(len(keep))
    mask = (new[us] >= 0) & (new[vs] >= 0)
    return RoadGraph(ids[keep], lat[keep], lon[keep], new[us[mask]], new[vs[mask]], ls[mask])


def load_osm_graph(place=config.PLACE, cache="caba_drive.graphml"):
    """Descarga (o lee de caché) la red vial de OpenStreetMap con OSMnx."""
    try:
        import osmnx as ox
    except ImportError:
        raise SystemExit("Falta osmnx. Instalalo con: pip install osmnx")
    if os.path.exists(cache):
        G = ox.load_graphml(cache)
    else:
        G = ox.graph_from_place(place, network_type="drive")
        ox.save_graphml(G, cache)
    ids = list(G.nodes)
    pos = {nid: i for i, nid in enumerate(ids)}
    lat = [G.nodes[n]["y"] for n in ids]
    lon = [G.nodes[n]["x"] for n in ids]
    edges = [(pos[u], pos[v], float(d["length"])) for u, v, d in G.edges(data=True)]
    return build_road_graph(ids, lat, lon, edges)


def make_synthetic_graph(n=45, spacing=120.0, p_oneway=0.35, seed=0):
    """Grilla urbana sintética (con calles de una mano y algunas diagonales),
    ubicada en Buenos Aires. Sirve para probar el código sin descargar el mapa.
    Las longitudes de arista son >= la distancia en línea recta, como en OSM."""
    rng = np.random.default_rng(seed)
    lat0, lon0 = -34.6037, -58.3816
    kx = 111320.0 * np.cos(np.radians(lat0))
    lat, lon = [], []
    for i in range(n):
        for j in range(n):
            x = j * spacing + rng.uniform(-15, 15)
            y = i * spacing + rng.uniform(-15, 15)
            lat.append(lat0 + y / 110574.0)
            lon.append(lon0 + x / kx)
    lat, lon = np.array(lat), np.array(lon)
    edges = []

    def add(u, v):
        d = float(haversine_vec(lat[u], lon[u], lat[v], lon[v]))
        edges.append((u, v, d * (1 + rng.uniform(0, 0.08))))

    for i in range(n):
        for j in range(n):
            u = i * n + j
            vecinos = []
            if j + 1 < n:
                vecinos.append(i * n + j + 1)
            if i + 1 < n:
                vecinos.append((i + 1) * n + j)
            if i + 1 < n and j + 1 < n and rng.random() < 0.03:
                vecinos.append((i + 1) * n + j + 1)  # diagonal
            for v in vecinos:
                r = rng.random()
                if r < p_oneway / 2:
                    add(u, v)
                elif r < p_oneway:
                    add(v, u)
                else:
                    add(u, v)
                    add(v, u)
    return build_road_graph(np.arange(n * n), lat, lon, edges)


def make_synthetic_hospitals(G, k=14, seed=1):
    rng = np.random.default_rng(seed)
    return [int(x) for x in rng.choice(G.n, size=k, replace=False)]


# --------------------------------------------------------------------------- #
# Hospitales
# --------------------------------------------------------------------------- #
def _norm(texto):
    t = unicodedata.normalize("NFKD", str(texto))
    return "".join(c for c in t if not unicodedata.combining(c)).lower()


def _campo_nombre(props, campo=None):
    if campo:
        return campo
    low = {k.lower(): k for k in props}
    for c in ("nombre", "name", "establecimiento", "hospital", "nom_hosp"):
        if c in low:
            return low[c]
    return None


def _punto(feat):
    geom = feat.get("geometry") or {}
    if geom.get("type") == "Point":
        lon, lat = geom["coordinates"][:2]
        return float(lat), float(lon)
    props = {k.lower(): v for k, v in (feat.get("properties") or {}).items()}
    for la, lo in (("lat", "long"), ("lat", "lon"), ("latitud", "longitud"), ("latitude", "longitude")):
        if la in props and lo in props:
            return float(props[la]), float(props[lo])
    return None


def load_hospitals(path, G, campo_nombre=None):
    """Lee el GeoJSON de hospitales del GCBA, se queda con los 14 generales de
    agudos (por nombre) y los ubica en el nodo más cercano del grafo.
    Devuelve (lista de nodos, lista de dicts con el detalle)."""
    with open(path, encoding="utf-8") as f:
        feats = json.load(f)["features"]
    if not feats:
        raise SystemExit("El GeoJSON no tiene registros.")
    campo = _campo_nombre(feats[0].get("properties") or {}, campo_nombre)
    if campo is None:
        raise SystemExit("No encontré el campo con el nombre del hospital. Campos disponibles: "
                         f"{list((feats[0].get('properties') or {}).keys())}. "
                         "Indicalo con --campo-nombre.")
    detalle, nodos = [], []
    for clave, oficial in config.HOSPITALES_AGUDOS.items():
        cands = [f for f in feats if clave in _norm((f.get("properties") or {}).get(campo, ""))]
        if len(cands) > 1:
            agudos = [f for f in cands if "agudos" in _norm(f["properties"].get(campo, ""))]
            cands = agudos or cands
            print(f"  Aviso: '{clave}' coincide con {len(cands)} registros; uso el primero.")
        if not cands:
            print(f"  Aviso: no encontré en el GeoJSON a {oficial}.")
            continue
        feat = cands[0]
        p = _punto(feat)
        if p is None:
            print(f"  Aviso: {oficial} no tiene coordenadas utilizables.")
            continue
        nodo, d = G.nearest(*p)
        if d > 500:
            print(f"  Aviso: {oficial} quedó a {d:.0f} m de su nodo más cercano.")
        if nodo in nodos:
            print(f"  Aviso: {oficial} cae en el mismo nodo que otro hospital.")
        else:
            nodos.append(nodo)
        detalle.append(dict(clave=clave, nombre=feat["properties"].get(campo), lat=p[0], lon=p[1],
                            nodo=nodo, dist_nodo_m=round(d, 1)))
    if not nodos:
        raise SystemExit("No se pudo ubicar ningún hospital.")
    print(f"Hospitales ubicados en el grafo: {len(nodos)} de {len(config.HOSPITALES_AGUDOS)}")
    return nodos, detalle
