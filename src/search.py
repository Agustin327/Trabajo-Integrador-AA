"""Algoritmos de búsqueda: BFS, UCS, A*, A* ponderado y greedy.

Todos usan el mismo problema (problem.py). Métricas devueltas:
  expandidos : estados sacados de la frontera y expandidos (sin contar la meta)
  generados  : estados insertados en la frontera
  costo      : tiempo total en segundos, recalculado sobre el camino final
"""
import heapq
import time
from collections import deque
from dataclasses import dataclass, field


@dataclass
class Result:
    algo: str
    found: bool
    cost: float = float("nan")
    phase1: float = float("nan")
    expanded: int = 0
    generated: int = 0
    max_frontier: int = 0
    time_s: float = 0.0
    path: list = field(default_factory=list)


def _reconstruct(parent, goal):
    path = []
    s = goal
    while s is not None:
        path.append(s)
        s = parent[s]
    return path[::-1]


def _finish(problem, algo, parent, goal, expanded, generated, max_frontier, t0):
    path = _reconstruct(parent, goal)
    cost, t1 = problem.path_metrics(path)
    return Result(algo, True, cost, t1, expanded, generated, max_frontier,
                  time.perf_counter() - t0, path)


def best_first(problem, mode, h=None, w=1.0, algo=None):
    """mode: 'ucs' (f=g), 'astar' (f=g+h), 'wastar' (f=g+w*h), 'greedy' (f=h)."""
    t0 = time.perf_counter()
    algo = algo or mode
    init = problem.initial
    hv = h(init) if h else 0.0
    g = {init: 0.0}
    parent = {init: None}
    counter = 0
    f0 = {"ucs": 0.0, "astar": hv, "wastar": w * hv, "greedy": hv}[mode]
    pq = [(f0, hv, counter, init, 0.0)]
    expanded, generated, max_frontier = 0, 1, 1
    while pq:
        _, _, _, s, gs = heapq.heappop(pq)
        if mode != "greedy" and gs > g[s] + 1e-12:
            continue  # entrada obsoleta (se encontró un camino mejor)
        if problem.is_goal(s):
            return _finish(problem, algo, parent, s, expanded, generated, max_frontier, t0)
        expanded += 1
        for s2, c in problem.successors(s):
            g2 = gs + c
            old = g.get(s2)
            if mode == "greedy":
                if old is not None:
                    continue
            elif old is not None and g2 >= old - 1e-12:
                continue
            g[s2] = g2
            parent[s2] = s
            h2 = h(s2) if h else 0.0
            counter += 1
            if mode == "ucs":
                item = (g2, 0.0, counter, s2, g2)
            elif mode == "astar":
                item = (g2 + h2, h2, counter, s2, g2)
            elif mode == "wastar":
                item = (g2 + w * h2, h2, counter, s2, g2)
            else:  # greedy
                item = (h2, g2, counter, s2, g2)
            heapq.heappush(pq, item)
            generated += 1
        if len(pq) > max_frontier:
            max_frontier = len(pq)
    return Result(algo, False, expanded=expanded, generated=generated,
                  max_frontier=max_frontier, time_s=time.perf_counter() - t0)


def bfs(problem, algo="bfs"):
    """Busca el camino con menos aristas (ignora los costos). Solo de referencia."""
    t0 = time.perf_counter()
    init = problem.initial
    parent = {init: None}
    if problem.is_goal(init):
        return _finish(problem, algo, parent, init, 0, 1, 1, t0)
    q = deque([init])
    expanded, generated, max_frontier = 0, 1, 1
    while q:
        s = q.popleft()
        expanded += 1
        for s2, _ in problem.successors(s):
            if s2 in parent:
                continue
            parent[s2] = s
            generated += 1
            if problem.is_goal(s2):
                return _finish(problem, algo, parent, s2, expanded, generated, max_frontier, t0)
            q.append(s2)
        if len(q) > max_frontier:
            max_frontier = len(q)
    return Result(algo, False, expanded=expanded, generated=generated,
                  max_frontier=max_frontier, time_s=time.perf_counter() - t0)


def run_algorithm(problem, name):
    """Nombres: bfs, ucs, astar_h2, greedy_h2, astar_h3, wastar_h2_1.5, ..."""
    if name == "bfs":
        return bfs(problem, name)
    if name == "ucs":
        return best_first(problem, "ucs", algo=name)
    partes = name.split("_")
    modo, hname = partes[0], partes[1]
    w = float(partes[2]) if len(partes) > 2 else 1.0
    if modo not in ("astar", "wastar", "greedy"):
        raise ValueError(f"Algoritmo desconocido: {name}")
    return best_first(problem, modo, problem.heuristic(hname), w=w, algo=name)
