"""Pruebas automáticas sobre un grafo sintético: python pruebas.py

Verifica:
  1. A* con h2 y UCS dan el mismo costo óptimo; los caminos son válidos.
  2. Greedy y BFS encuentran solución; A* ponderado respeta su cota w * óptimo.
  3. h2 es admisible y consistente (comparando con el costo real hasta la meta).
  4. El filtro de los 14 hospitales funciona con tildes y descarta otros hospitales.
"""
import json
import os
import tempfile

import numpy as np
from scipy.sparse.csgraph import dijkstra

import config
from data import load_hospitals, make_synthetic_graph, make_synthetic_hospitals
from experiments import generar_casos
from problem import AmbulanceProblem, HospitalContext
from search import run_algorithm

EPS = 1e-9


def main():
    G = make_synthetic_graph(n=30, seed=3)
    hosp = make_synthetic_hospitals(G, seed=4)
    ctx = HospitalContext(G, hosp)
    print(f"Grafo de prueba: {G.n} nodos, {G.n_edges} aristas; {len(hosp)} hospitales")
    casos = generar_casos(G, hosp, 8, seed=7, corto_max=1000, largo_min=2500)
    assert len(casos) == 24, f"se esperaban 24 casos, hay {len(casos)}"

    # 1 y 2: optimalidad y validez ------------------------------------------------
    peor_w = 0.0
    for caso in casos:
        p = AmbulanceProblem(G, ctx, caso["start"], caso["incident"])
        ucs = run_algorithm(p, "ucs")
        ast = run_algorithm(p, "astar_h2")
        gre = run_algorithm(p, "greedy_h2")
        bfs = run_algorithm(p, "bfs")
        w15 = run_algorithm(p, "wastar_h2_1.5")
        for r in (ucs, ast, gre, bfs, w15):
            assert r.found and p.is_goal(r.path[-1]) and r.path[0] == p.initial
            assert any(s[1] == 1 and s[0] == p.incident for s in r.path), "no pasó por el incidente"
        assert abs(ucs.cost - ast.cost) < 1e-6, (ucs.cost, ast.cost)
        assert ast.expanded <= ucs.expanded, "A* expandió más que UCS"
        assert gre.cost >= ucs.cost - 1e-6 and bfs.cost >= ucs.cost - 1e-6
        assert w15.cost <= 1.5 * ucs.cost + 1e-6, "A* ponderado violó su cota"
        peor_w = max(peor_w, w15.cost / ucs.cost)
    print(f"[1-2] OK en {len(casos)} casos: A*(h2) = UCS; BFS, greedy y A* ponderado válidos "
          f"(peor A* ponderado w=1,5: x{peor_w:.3f})")

    # 3: admisibilidad y consistencia de h2 ---------------------------------------
    Gt = G.csr.T.tocsr()
    d_hosp = dijkstra(Gt, directed=True, indices=hosp, min_only=True)  # calle: nodo -> hospital más cercano
    n_h3_mal = 0
    for caso in casos[::4]:
        p = AmbulanceProblem(G, ctx, caso["start"], caso["incident"])
        h2 = p.heuristic("h2")
        h3 = p.heuristic("h3")
        d_inc = dijkstra(Gt, directed=True, indices=p.incident)  # calle: nodo -> incidente
        for n in range(G.n):
            real1 = d_hosp[n] / p.v
            real0 = (d_inc[n] + d_hosp[p.incident]) / p.v
            assert h2((n, 1)) <= real1 + EPS, "h2 no admisible en fase 1"
            assert h2((n, 0)) <= real0 + EPS, "h2 no admisible en fase 0"
            n_h3_mal += (h3((n, 1)) > real1 + EPS) + (h3((n, 0)) > real0 + EPS)
        for (u, w), l in G.elen.items():
            c = l / p.v
            assert h2((u, 1)) <= c + h2((w, 1)) + EPS, "h2 no consistente (fase 1)"
            nph = 1 if w == p.incident else 0
            assert h2((u, 0)) <= c + h2((w, nph)) + EPS, "h2 no consistente (fase 0)"
    print(f"[3] OK: h2 admisible y consistente. (Manhattan h3 sobreestimó en {n_h3_mal} estados: "
          "es el contraejemplo esperado)")

    # 4: filtro de hospitales con un GeoJSON de prueba ---------------------------
    nombres = [v for v in config.HOSPITALES_AGUDOS.values()]
    extras = ["Hospital General de Niños Pedro de Elizalde", "Hospital de Emergencias Psiquiátricas Torcuato de Alvear",
              "Sanatorio Privado Ejemplo"]
    rng = np.random.default_rng(0)
    feats = []
    for i, nom in enumerate(nombres + extras):
        k = int(rng.integers(G.n))
        feats.append({"type": "Feature", "properties": {"NOMBRE": nom.upper() if i % 2 else nom},
                      "geometry": {"type": "Point", "coordinates": [float(G.lon[k]), float(G.lat[k])]}})
    with tempfile.TemporaryDirectory() as tmp:
        ruta = os.path.join(tmp, "hospitales_prueba.geojson")
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump({"type": "FeatureCollection", "features": feats}, f, ensure_ascii=False)
        nodos, detalle = load_hospitals(ruta, G)
    assert len(detalle) == 14, f"se esperaban 14 hospitales, se ubicaron {len(detalle)}"
    assert all("Elizalde" not in d["nombre"] and "Alvear" not in d["nombre"] for d in detalle)
    print("[4] OK: el filtro deja los 14 hospitales generales de agudos y descarta el resto")
    print("\nTodas las pruebas pasaron.")


if __name__ == "__main__":
    main()
