"""Experimentos: casos al azar (semilla fija) y comparación de algoritmos.

Ejemplos:
  # Prueba rápida con un grafo sintético (no necesita descargar nada)
  python src/experiments.py --fuente sintetico --n 10 --corto-max 1500 --largo-min 3500

  # Con datos reales (OSM + GeoJSON de hospitales del GCBA)
  python src/experiments.py --fuente osm --hospitales data/hospitales.geojson --n 20
"""
import argparse
import os

import numpy as np
import pandas as pd
from scipy.sparse.csgraph import dijkstra

import config
from data import (load_hospitals, load_osm_graph, make_synthetic_graph,
                  make_synthetic_hospitals)
from problem import AmbulanceProblem, HospitalContext
from search import run_algorithm

ALGOS_DEFECTO = "bfs,ucs,astar_h2,greedy_h2,wastar_h2_1.5,astar_h3"
ORDEN_CAT = ["corto", "medio", "largo"]


def generar_casos(G, hosp_nodes, n_por_cat, seed, corto_max, largo_min):
    """Cada caso: la ambulancia parte de un hospital al azar y el incidente es un
    nodo al azar cuya distancia por calle (fase 1) cae en la categoría pedida."""
    rng = np.random.default_rng(seed)
    D = dijkstra(G.csr, directed=True, indices=hosp_nodes)  # metros, (H, N)
    rangos = {"corto": (0.0, corto_max), "medio": (corto_max, largo_min), "largo": (largo_min, np.inf)}
    casos = []
    for cat in ORDEN_CAT:
        lo, hi = rangos[cat]
        cands = []
        for i in range(len(hosp_nodes)):
            d = D[i]
            cands.append(np.flatnonzero(np.isfinite(d) & (d > lo) & (d <= hi)))
        con_datos = [i for i, c in enumerate(cands) if len(c)]
        if not con_datos:
            print(f"  Aviso: no hay incidentes posibles en la categoría '{cat}'; se omite.")
            continue
        for _ in range(n_por_cat):
            i = int(rng.choice(con_datos))
            inc = int(rng.choice(cands[i]))
            casos.append(dict(categoria=cat, start=hosp_nodes[i], incident=inc,
                              dist_fase1_m=float(D[i][inc])))
    return casos


def correr(G, ctx, casos, algos):
    filas = []
    for ci, caso in enumerate(casos):
        prob = AmbulanceProblem(G, ctx, caso["start"], caso["incident"])
        for a in algos:
            r = run_algorithm(prob, a)
            filas.append(dict(
                caso=ci, categoria=caso["categoria"], algo=a, encontrado=r.found,
                costo_s=r.cost, t_fase1_s=r.phase1, dist_m=r.cost * ctx.v,
                expandidos=r.expanded, generados=r.generated,
                frontera_max=r.max_frontier, t_cpu_s=r.time_s))
    df = pd.DataFrame(filas)
    ref = df[df.algo == "ucs"].set_index("caso").costo_s
    df["costo_ucs_s"] = df.caso.map(ref)
    df["subopt_pct"] = (df.costo_s / df.costo_ucs_s - 1.0) * 100.0
    df["optimo"] = df.subopt_pct <= 1e-6
    return df


def resumen(df):
    df = df.copy()
    df["categoria"] = pd.Categorical(df.categoria, ORDEN_CAT, ordered=True)
    out = df.groupby(["categoria", "algo"], observed=True, sort=False).agg(
        expandidos=("expandidos", "mean"), generados=("generados", "mean"),
        t_cpu_ms=("t_cpu_s", lambda x: x.mean() * 1000),
        tiempo_total_min=("costo_s", lambda x: x.mean() / 60),
        subopt_pct=("subopt_pct", "mean"), pct_optimo=("optimo", lambda x: x.mean() * 100),
    ).round(2)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fuente", choices=["osm", "sintetico"], default="sintetico")
    ap.add_argument("--graphml", default="caba_drive.graphml", help="caché del grafo de OSM")
    ap.add_argument("--hospitales", default="data/hospitales.geojson")
    ap.add_argument("--campo-nombre", default=None, help="campo del GeoJSON con el nombre del hospital")
    ap.add_argument("--n", type=int, default=20, help="casos por categoría")
    ap.add_argument("--seed", type=int, default=config.SEED)
    ap.add_argument("--corto-max", type=float, default=config.UMBRAL_CORTO_M)
    ap.add_argument("--largo-min", type=float, default=config.UMBRAL_LARGO_M)
    ap.add_argument("--algos", default=ALGOS_DEFECTO)
    ap.add_argument("--v-kmh", type=float, default=config.V_KMH)
    ap.add_argument("--sensibilidad", default="35,46,55", help="velocidades (km/h) para mostrar tiempos")
    ap.add_argument("--salida", default="resultados")
    a = ap.parse_args()

    v_ms = a.v_kmh / 3.6
    if a.fuente == "osm":
        print("Cargando grafo de OpenStreetMap...")
        G = load_osm_graph(cache=a.graphml)
        hosp, _ = load_hospitals(a.hospitales, G, a.campo_nombre)
    else:
        print("Usando grafo sintético (solo para pruebas).")
        G = make_synthetic_graph(seed=a.seed)
        hosp = make_synthetic_hospitals(G, seed=a.seed + 1)
    print(f"Grafo: {G.n} nodos, {G.n_edges} aristas dirigidas. Hospitales: {len(hosp)}. v = {a.v_kmh} km/h")

    ctx = HospitalContext(G, hosp, v_ms)
    casos = generar_casos(G, hosp, a.n, a.seed, a.corto_max, a.largo_min)
    print(f"Casos generados: {len(casos)} (semilla {a.seed})")
    df = correr(G, ctx, casos, a.algos.split(","))

    os.makedirs(a.salida, exist_ok=True)
    df.to_csv(os.path.join(a.salida, "resultados.csv"), index=False)
    res = resumen(df)
    res.to_csv(os.path.join(a.salida, "resumen.csv"))
    print("\nResumen por categoría y algoritmo (promedios):")
    print(res.to_string())

    # Control: A* con h2 debe dar el mismo costo que UCS (h2 es admisible)
    ast = df[df.algo == "astar_h2"]
    if len(ast):
        dif = (ast.costo_s - ast.costo_ucs_s).abs().max()
        print(f"\nControl de optimalidad: máxima diferencia A*(h2) vs UCS = {dif:.3e} s")

    # Sensibilidad a la velocidad (el camino óptimo no cambia, solo los tiempos)
    ucs = df[df.algo == "ucs"].copy()
    if len(ucs) and a.sensibilidad:
        print("\nTiempo total promedio de la ruta óptima (min) según la velocidad:")
        vs = [float(x) for x in a.sensibilidad.split(",")]
        filas = {}
        for cat, g in ucs.groupby("categoria"):
            filas[cat] = {f"{v:g} km/h": round(g.dist_m.mean() / (v / 3.6) / 60, 1) for v in vs}
        print(pd.DataFrame(filas).T.reindex(ORDEN_CAT).dropna(how="all").to_string())
    print(f"\nResultados guardados en '{a.salida}/'.")


if __name__ == "__main__":
    main()
