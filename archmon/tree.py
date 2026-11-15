"""Режим дерева процессов (как F5 в htop) со сворачиваемыми ветками. Без Qt, легко проверить отдельно."""
from collections import defaultdict
from dataclasses import dataclass
from operator import attrgetter
from typing import Optional


@dataclass
class TreeNode:
    proc: object
    prefix: str                    # линии дерева для колонки Command: «├─ », «└─ », «│  » (без стрелки)
    parent_pid: Optional[int]      # родитель в этом дереве; None у корней
    has_children: bool = False
    descendants: int = 0           # сколько потомков всего (показывается у свёрнутой ветки)


def tree_nodes(procs, key, descending):
    """Все процессы в порядке «родитель, затем его дети». Дети каждого родителя сортируются по key.

    Если родителя нет в списке (отфильтрован или относится к другой группе), процесс становится корнем.
    """
    present = {p.pid for p in procs}
    children, roots = defaultdict(list), []
    for p in procs:
        if p.ppid in present and p.ppid != p.pid:
            children[p.ppid].append(p)
        else:
            roots.append(p)

    by_key = attrgetter(key)
    out = []

    def walk(proc, parent_pid, guide, is_last, depth):
        node = TreeNode(proc, "" if depth == 0 else guide + ("└─ " if is_last else "├─ "), parent_pid)
        out.append(node)
        kids = sorted(children.get(proc.pid, []), key=by_key, reverse=descending)
        next_guide = "" if depth == 0 else guide + ("   " if is_last else "│  ")
        total = 0
        for i, kid in enumerate(kids):
            total += 1 + walk(kid, proc.pid, next_guide, i == len(kids) - 1, depth + 1)
        node.has_children, node.descendants = bool(kids), total
        return total

    for root in sorted(roots, key=by_key, reverse=descending):
        walk(root, None, "", True, 0)
    return out


def visible_nodes(nodes, expanded, show_all=False):
    """Какие узлы видны: корни всегда, остальные только если раскрыты все их предки.

    expanded: множество PID раскрытых узлов; show_all=True раскрывает всё (например, при фильтре).
    """
    visible, shown = {}, []
    for node in nodes:
        parent = node.parent_pid
        ok = parent is None or (visible.get(parent, False) and (show_all or parent in expanded))
        visible[node.proc.pid] = ok
        if ok:
            shown.append(node)
    return shown
