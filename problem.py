"""Formulación del problema de búsqueda: ambulancia -> incidente -> hospital.

Estado:      (nodo, fase), fase 0 = hacia el paciente, fase 1 = hacia el hospital.
Inicial:     (nodo_ambulancia, 0)  (si ya está en el incidente, fase 1).
Acciones:    avanzar por una arista saliente (respeta sentidos de calle).
Transición:  al llegar al nodo del incidente en fase 0, pasa a fase 1 (costo 0).
Meta:        estar en un nodo de hospital en fase 1.
Costo:       longitud / velocidad (segundos), con velocidad constante.
"""
import numpy as np

import config
from data import haversine_vec, manhattan_vec


class HospitalContext:
    """Distancias de todos los nodos al hospital más cercano (se calculan una vez)."""

    def __init__(self, G, hosp_nodes, v_ms=config.V_MS):
        self.nodes = list(hosp_nodes)
        self.set = frozenset(self.nodes)
        self.v = v_ms
        d = np.full(G.n, np.inf)
        m = np.full(G.n, np.inf)
        for h in self.nodes:
            d = np.minimum(d, G.haversine_to(G.lat[h], G.lon[h]))
            m = np.minimum(m, manhattan_vec(G.lat, G.lon, G.lat[h], G.lon[h]))
        self.d_hosp_t = (d / v_ms).tolist()   # segundos, en línea recta
        self.m_hosp_t = (m / v_ms).tolist()   # segundos, Manhattan


class AmbulanceProblem:
    def __init__(self, G, ctx, start, incident):
        self.G = G
        self.ctx = ctx
        self.v = ctx.v
        self.start = int(start)
        self.incident = int(incident)
        self.initial = (self.start, 1 if self.start == self.incident else 0)
        self.hosp_set = ctx.set
        self._h = {}

    # -- problema ---------------------------------------------------------- #
    def is_goal(self, s):
        return s[1] == 1 and s[0] in self.hosp_set

    def successors(self, s):
        u, ph = s
        inc, v = self.incident, self.v
        for w, l in self.G.adj[u]:
            yield (w, 1 if (ph == 0 and w == inc) else ph), l / v

    # -- heurísticas ------------------------------------------------------- #
    def heuristic(self, name):
        if name in self._h:
            return self._h[name]
        G, inc, v = self.G, self.incident, self.v
        if name == "h0":
            h = lambda s: 0.0
        elif name == "h2":
            # Admisible y consistente: línea recta / velocidad.
            # Fase 0: tramo hasta el incidente + (incidente -> hospital más cercano).
            # Fase 1: hospital más cercano.
            d_inc = (G.haversine_to(G.lat[inc], G.lon[inc]) / v).tolist()
            d_h = self.ctx.d_hosp_t
            resto = d_h[inc]

            def h(s):
                n, ph = s
                return d_inc[n] + resto if ph == 0 else d_h[n]
        elif name == "h3":
            # Manhattan: contraejemplo, puede sobreestimar (no admisible).
            m_inc = (manhattan_vec(G.lat, G.lon, G.lat[inc], G.lon[inc]) / v).tolist()
            m_h = self.ctx.m_hosp_t
            resto = m_h[inc]

            def h(s):
                n, ph = s
                return m_inc[n] + resto if ph == 0 else m_h[n]
        else:
            raise ValueError(f"Heurística desconocida: {name}")
        self._h[name] = h
        return h

    # -- utilidades -------------------------------------------------------- #
    def path_metrics(self, path):
        """Costo total y tiempo de la fase 1 recorriendo el camino (lanza KeyError
        si algún paso no es una arista válida del grafo)."""
        cost, t1 = 0.0, (0.0 if path[0][1] == 1 else None)
        for (u, _), (w, ph2) in zip(path, path[1:]):
            cost += self.G.elen[(u, w)] / self.v
            if t1 is None and ph2 == 1:
                t1 = cost
        return cost, t1
