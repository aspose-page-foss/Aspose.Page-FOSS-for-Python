"""Pure-Python port of Clipper (subset needed for OffsetPaths)."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import List, Optional


@dataclass
class IntPoint:
    x: int
    y: int


@dataclass
class DoublePoint:
    x: float = 0.0
    y: float = 0.0


@dataclass
class IntRect:
    left: int = 0
    top: int = 0
    right: int = 0
    bottom: int = 0


class ClipType:
    ctIntersection = 0
    ctUnion = 1
    ctDifference = 2
    ctXor = 3


class PolyType:
    ptSubject = 0
    ptClip = 1


class PolyFillType:
    pftEvenOdd = 0
    pftNonZero = 1
    pftPositive = 2
    pftNegative = 3


class JoinType:
    jtSquare = 0
    jtRound = 1
    jtMiter = 2


class EndType:
    etClosed = 0
    etButt = 1
    etSquare = 2
    etRound = 3


class EdgeSide:
    esLeft = 0
    esRight = 1


class Direction:
    dRightToLeft = 0
    dLeftToRight = 1


class ClipperException(Exception):
    pass


class PolyNode:
    def __init__(self) -> None:
        self.parent: Optional["PolyNode"] = None
        self.polygon: List[IntPoint] = []
        self.index: int = 0
        self.childs: List["PolyNode"] = []
        self.is_open: bool = False

    def add_child(self, child: "PolyNode") -> None:
        child.parent = self
        child.index = len(self.childs)
        self.childs.append(child)

    @property
    def is_hole(self) -> bool:
        result = True
        node = self.parent
        while node is not None:
            result = not result
            node = node.parent
        return result

    @property
    def contour(self) -> List[IntPoint]:
        return self.polygon

    @property
    def child_count(self) -> int:
        return len(self.childs)


class PolyTree(PolyNode):
    def __init__(self) -> None:
        super().__init__()
        self.all_polys: List[PolyNode] = []

    def clear(self) -> None:
        self.all_polys.clear()
        self.childs.clear()

    def get_first(self) -> Optional[PolyNode]:
        return self.childs[0] if self.childs else None

    @property
    def total(self) -> int:
        return len(self.all_polys)


class TEdge:
    def __init__(self) -> None:
        self.bot: IntPoint = IntPoint(0, 0)
        self.curr: IntPoint = IntPoint(0, 0)
        self.top: IntPoint = IntPoint(0, 0)
        self.delta: IntPoint = IntPoint(0, 0)
        self.dx: float = 0.0
        self.poly_typ: int = PolyType.ptSubject
        self.side: int = EdgeSide.esLeft
        self.wind_delta: int = 0
        self.wind_cnt: int = 0
        self.wind_cnt2: int = 0
        self.out_idx: int = -1
        self.next: Optional["TEdge"] = None
        self.prev: Optional["TEdge"] = None
        self.next_in_lml: Optional["TEdge"] = None
        self.next_in_ael: Optional["TEdge"] = None
        self.prev_in_ael: Optional["TEdge"] = None
        self.next_in_sel: Optional["TEdge"] = None
        self.prev_in_sel: Optional["TEdge"] = None


class IntersectNode:
    def __init__(self) -> None:
        self.edge1: Optional[TEdge] = None
        self.edge2: Optional[TEdge] = None
        self.pt: IntPoint = IntPoint(0, 0)
        self.next: Optional["IntersectNode"] = None


class LocalMinima:
    def __init__(self) -> None:
        self.y: int = 0
        self.left_bound: Optional[TEdge] = None
        self.right_bound: Optional[TEdge] = None
        self.next: Optional["LocalMinima"] = None


class Scanbeam:
    def __init__(self, y: int = 0) -> None:
        self.y = y
        self.next: Optional["Scanbeam"] = None


class OutRec:
    def __init__(self) -> None:
        self.idx: int = -1
        self.is_hole: bool = False
        self.is_open: bool = False
        self.first_left: Optional["OutRec"] = None
        self.pts: Optional["OutPt"] = None
        self.bottom_pt: Optional["OutPt"] = None
        self.poly_node: Optional[PolyNode] = None


class OutPt:
    def __init__(self) -> None:
        self.idx: int = -1
        self.pt: IntPoint = IntPoint(0, 0)
        self.next: Optional["OutPt"] = None
        self.prev: Optional["OutPt"] = None


class Join:
    def __init__(self) -> None:
        self.out_pt1: Optional[OutPt] = None
        self.out_pt2: Optional[OutPt] = None
        self.off_pt: IntPoint = IntPoint(0, 0)


class ClipperBase:
    horizontal = -3.4e38
    skip = -2
    unassigned = -1
    tolerance = 1.0e-20

    def __init__(self) -> None:
        self.minima_list: Optional[LocalMinima] = None
        self.current_lm: Optional[LocalMinima] = None
        self.edges: List[List[TEdge]] = []
        self.use_full_range = True
        self.has_open_paths = False
        self.preserve_collinear = False

    @staticmethod
    def near_zero(val: float) -> bool:
        return -ClipperBase.tolerance < val < ClipperBase.tolerance

    @staticmethod
    def is_horizontal(e: TEdge) -> bool:
        return e.delta.y == 0

    def point_is_vertex(self, pt: IntPoint, pp: OutPt) -> bool:
        pp2 = pp
        while True:
            if pp2.pt == pt:
                return True
            pp2 = pp2.next  # type: ignore
            if pp2 == pp:
                break
        return False

    def point_on_line_segment(self, pt: IntPoint, line_pt1: IntPoint, line_pt2: IntPoint) -> bool:
        return (
            (pt.x == line_pt1.x and pt.y == line_pt1.y)
            or (pt.x == line_pt2.x and pt.y == line_pt2.y)
            or (
                ((pt.x > line_pt1.x) == (pt.x < line_pt2.x))
                and ((pt.y > line_pt1.y) == (pt.y < line_pt2.y))
                and (pt.x - line_pt1.x) * (line_pt2.y - line_pt1.y)
                == (line_pt2.x - line_pt1.x) * (pt.y - line_pt1.y)
            )
        )

    def point_on_polygon(self, pt: IntPoint, pp: OutPt) -> bool:
        pp2 = pp
        while True:
            if self.point_on_line_segment(pt, pp2.pt, pp2.next.pt):  # type: ignore
                return True
            pp2 = pp2.next  # type: ignore
            if pp2 == pp:
                break
        return False

    def point_in_polygon(self, pt: IntPoint, pp: OutPt) -> bool:
        pp2 = pp
        result = False
        while True:
            if (
                ((pp2.pt.y <= pt.y < pp2.prev.pt.y) or (pp2.prev.pt.y <= pt.y < pp2.pt.y))
                and (pt.x - pp2.pt.x) < (pp2.prev.pt.x - pp2.pt.x) * (pt.y - pp2.pt.y) / (pp2.prev.pt.y - pp2.pt.y)
            ):
                result = not result
            pp2 = pp2.next  # type: ignore
            if pp2 == pp:
                break
        return result

    @staticmethod
    def slopes_equal(e1: TEdge, e2: TEdge) -> bool:
        return e1.delta.y * e2.delta.x == e1.delta.x * e2.delta.y

    @staticmethod
    def slopes_equal_pts(pt1: IntPoint, pt2: IntPoint, pt3: IntPoint) -> bool:
        return (pt1.y - pt2.y) * (pt2.x - pt3.x) - (pt1.x - pt2.x) * (pt2.y - pt3.y) == 0

    @staticmethod
    def slopes_equal_pts4(pt1: IntPoint, pt2: IntPoint, pt3: IntPoint, pt4: IntPoint) -> bool:
        return (pt1.y - pt2.y) * (pt3.x - pt4.x) - (pt1.x - pt2.x) * (pt3.y - pt4.y) == 0

    def clear(self) -> None:
        self.minima_list = None
        self.current_lm = None
        self.edges.clear()
        self.use_full_range = True
        self.has_open_paths = False

    def range_test(self, pt: IntPoint) -> None:
        return

    def init_edge(self, e: TEdge, e_next: TEdge, e_prev: TEdge, pt: IntPoint) -> None:
        e.next = e_next
        e.prev = e_prev
        e.curr = pt
        e.out_idx = self.unassigned

    def init_edge2(self, e: TEdge, poly_type: int) -> None:
        if e.curr.y >= e.next.curr.y:  # type: ignore
            e.bot = e.curr
            e.top = e.next.curr  # type: ignore
        else:
            e.top = e.curr
            e.bot = e.next.curr  # type: ignore
        self.set_dx(e)
        e.poly_typ = poly_type

    def add_path(self, pg: List[IntPoint], poly_type: int, closed: bool) -> bool:
        if not closed:
            raise ClipperException("AddPath: Open paths have been disabled.")
        high_i = len(pg) - 1
        closed_or_semi = high_i > 0 and (closed or (pg[0] == pg[high_i]))
        while high_i > 0 and pg[high_i] == pg[0]:
            high_i -= 1
        while high_i > 0 and pg[high_i] == pg[high_i - 1]:
            high_i -= 1
        if closed and high_i < 2:
            return False
        edges: List[TEdge] = [TEdge() for _ in range(high_i + 1)]
        try:
            edges[1].curr = pg[1]
            self.range_test(pg[0])
            self.range_test(pg[high_i])
            self.init_edge(edges[0], edges[1], edges[high_i], pg[0])
            self.init_edge(edges[high_i], edges[0], edges[high_i - 1], pg[high_i])
            for i in range(high_i - 1, 0, -1):
                self.range_test(pg[i])
                self.init_edge(edges[i], edges[i + 1], edges[i - 1], pg[i])
        except Exception:
            return False
        e_start = edges[0]
        if not closed_or_semi:
            e_start.prev.out_idx = self.skip  # type: ignore
        e = e_start
        e_loop_stop = e_start
        while True:
            if e.curr == e.next.curr:  # type: ignore
                if e == e_start:
                    e_start = e.next  # type: ignore
                e = self.remove_edge(e)
                e_loop_stop = e
                continue
            if e.prev == e.next:
                break
            if (
                closed_or_semi
                and self.slopes_equal_pts(e.prev.curr, e.curr, e.next.curr)  # type: ignore
            ):
                if closed and (not self.preserve_collinear or not self.pt2_is_between_pt1_and_pt3(e.prev.curr, e.curr, e.next.curr)):  # type: ignore
                    if e == e_start:
                        e_start = e.next  # type: ignore
                    e = self.remove_edge(e)
                    e = e.prev  # type: ignore
                    e_loop_stop = e
                    continue
            e = e.next  # type: ignore
            if e == e_loop_stop:
                break
        if (not closed and e == e.next) or (closed and e.prev == e.next):
            return False
        self.edges.append(edges)
        e_highest = e_start
        e = e_start
        while True:
            self.init_edge2(e, poly_type)
            if e.top.y < e_highest.top.y:
                e_highest = e
            e = e.next  # type: ignore
            if e == e_start:
                break
        if self.all_horizontal(e):
            if closed_or_semi:
                e.prev.out_idx = self.skip  # type: ignore
            self.ascend_to_max(e, False, False)
            return True
        e = e_start.prev  # type: ignore
        if e.prev == e.next:
            e_highest = e.next  # type: ignore
        else:
            e = e_highest
            while self.is_horizontal(e_highest) or (e_highest.top == e_highest.next.top) or (e_highest.top == e_highest.next.bot):  # type: ignore
                e_highest = e_highest.next  # type: ignore
                if e_highest == e:
                    while self.is_horizontal(e_highest) or not self.shared_vert_with_prev_at_top(e_highest):
                        e_highest = e_highest.next  # type: ignore
                    break
        e = e_highest
        while True:
            e = self.add_bounds_to_lml(e, closed)
            if e == e_highest:
                break
        return True

    def add_paths(self, ppg: List[List[IntPoint]], poly_type: int, closed: bool) -> bool:
        result = False
        for path in ppg:
            if self.add_path(path, poly_type, closed):
                result = True
        return result

    def pt2_is_between_pt1_and_pt3(self, pt1: IntPoint, pt2: IntPoint, pt3: IntPoint) -> bool:
        if pt1 == pt3 or pt1 == pt2 or pt3 == pt2:
            return False
        if pt1.x != pt3.x:
            return (pt2.x > pt1.x) == (pt2.x < pt3.x)
        return (pt2.y > pt1.y) == (pt2.y < pt3.y)

    def remove_edge(self, e: TEdge) -> TEdge:
        e.prev.next = e.next  # type: ignore
        e.next.prev = e.prev  # type: ignore
        result = e.next  # type: ignore
        e.prev = None
        return result

    def get_last_horz(self, edge: TEdge) -> TEdge:
        result = edge
        while result.out_idx != self.skip and result.next != edge and self.is_horizontal(result.next):  # type: ignore
            result = result.next  # type: ignore
        return result

    def shared_vert_with_prev_at_top(self, edge: TEdge) -> bool:
        e = edge
        result = True
        while e.prev != edge:
            if e.top == e.prev.top:
                if e.bot == e.prev.bot:
                    e = e.prev
                    continue
                result = True
            else:
                result = False
            break
        while e != edge:
            result = not result
            e = e.next  # type: ignore
        return result

    def shared_vert_with_next_is_bot(self, edge: TEdge) -> bool:
        result = True
        e = edge
        while e.prev != edge:
            a = e.next.bot == e.bot  # type: ignore
            b = e.prev.bot == e.bot  # type: ignore
            if a != b:
                result = a
                break
            a = e.next.top == e.top  # type: ignore
            b = e.prev.top == e.top  # type: ignore
            if a != b:
                result = b
                break
            e = e.prev
        while e != edge:
            result = not result
            e = e.next  # type: ignore
        return result

    def more_below(self, edge: TEdge) -> bool:
        e = edge
        if self.is_horizontal(e):
            while self.is_horizontal(e.next):  # type: ignore
                e = e.next  # type: ignore
            return e.next.bot.y > e.bot.y  # type: ignore
        if self.is_horizontal(e.next):  # type: ignore
            while self.is_horizontal(e.next):  # type: ignore
                e = e.next  # type: ignore
            return e.next.bot.y > e.bot.y  # type: ignore
        return e.bot == e.next.top  # type: ignore

    def just_before_loc_min(self, edge: TEdge) -> bool:
        e = edge
        if self.is_horizontal(e):
            while self.is_horizontal(e.next):  # type: ignore
                e = e.next  # type: ignore
            return e.next.top.y < e.bot.y  # type: ignore
        return self.shared_vert_with_next_is_bot(e)

    def more_above(self, edge: TEdge) -> bool:
        if self.is_horizontal(edge):
            edge = self.get_last_horz(edge)
            return edge.next.top.y < edge.top.y  # type: ignore
        if self.is_horizontal(edge.next):  # type: ignore
            edge = self.get_last_horz(edge.next)  # type: ignore
            return edge.next.top.y < edge.top.y  # type: ignore
        return edge.next.top.y < edge.top.y  # type: ignore

    def all_horizontal(self, edge: TEdge) -> bool:
        if not self.is_horizontal(edge):
            return False
        e = edge.next  # type: ignore
        while e != edge:
            if not self.is_horizontal(e):
                return False
            e = e.next  # type: ignore
        return True

    def set_dx(self, e: TEdge) -> None:
        e.delta = IntPoint(e.top.x - e.bot.x, e.top.y - e.bot.y)
        if e.delta.y == 0:
            e.dx = self.horizontal
        else:
            e.dx = e.delta.x / e.delta.y

    def do_minima_lml(self, e1: Optional[TEdge], e2: Optional[TEdge], is_closed: bool) -> None:
        if e1 is None:
            if e2 is None:
                return
            new_lm = LocalMinima()
            new_lm.y = e2.bot.y
            new_lm.left_bound = None
            e2.wind_delta = 0
            new_lm.right_bound = e2
            self.insert_local_minima(new_lm)
            return
        new_lm = LocalMinima()
        new_lm.y = e1.bot.y
        if self.is_horizontal(e2):  # type: ignore
            if e2.bot.x != e1.bot.x:
                self.reverse_horizontal(e2)  # type: ignore
            new_lm.left_bound = e1
            new_lm.right_bound = e2
        elif e2.dx < e1.dx:  # type: ignore
            new_lm.left_bound = e1
            new_lm.right_bound = e2
        else:
            new_lm.left_bound = e2
            new_lm.right_bound = e1
        new_lm.left_bound.side = EdgeSide.esLeft  # type: ignore
        new_lm.right_bound.side = EdgeSide.esRight  # type: ignore
        if not is_closed:
            new_lm.left_bound.wind_delta = 0  # type: ignore
        elif new_lm.left_bound.next == new_lm.right_bound:
            new_lm.left_bound.wind_delta = -1  # type: ignore
        else:
            new_lm.left_bound.wind_delta = 1  # type: ignore
        new_lm.right_bound.wind_delta = -new_lm.left_bound.wind_delta  # type: ignore
        self.insert_local_minima(new_lm)

    def descend_to_min(self, e: TEdge) -> TEdge:
        e.next_in_lml = None
        if self.is_horizontal(e):
            e_horz = e
            while self.is_horizontal(e_horz.next):  # type: ignore
                e_horz = e_horz.next  # type: ignore
            if e_horz.bot != e_horz.next.top:  # type: ignore
                self.reverse_horizontal(e)
        while True:
            e = e.next  # type: ignore
            if e.out_idx == self.skip:
                break
            if self.is_horizontal(e):
                e_horz = self.get_last_horz(e)
                if e_horz == e.prev or (
                    e_horz.next.top.y < e.top.y and e_horz.next.bot.x > e.prev.bot.x  # type: ignore
                ):
                    break
                if e.top.x != e.prev.bot.x:
                    self.reverse_horizontal(e)
                if e_horz.out_idx == self.skip:
                    e_horz = e_horz.prev  # type: ignore
                while e != e_horz:
                    e.next_in_lml = e.prev
                    e = e.next  # type: ignore
                    if e.top.x != e.prev.bot.x:
                        self.reverse_horizontal(e)
            elif e.bot.y == e.prev.bot.y:
                break
            e.next_in_lml = e.prev
        return e.prev  # type: ignore

    def ascend_to_max(self, e: TEdge, appending: bool, is_closed: bool) -> None:
        if e.out_idx == self.skip:
            e = e.next  # type: ignore
            if not self.more_above(e.prev):
                return
        if self.is_horizontal(e) and appending and (e.bot != e.prev.bot):
            self.reverse_horizontal(e)
        e_start = e
        while True:
            if e.next.out_idx == self.skip or (
                e.next.top.y == e.top.y and not self.is_horizontal(e.next)
            ):
                break
            e.next_in_lml = e.next
            e = e.next  # type: ignore
            if self.is_horizontal(e) and (e.bot.x != e.prev.top.x):
                self.reverse_horizontal(e)
        if not appending:
            if e_start.out_idx == self.skip:
                e_start = e_start.next  # type: ignore
            if e_start != e.next:
                self.do_minima_lml(None, e_start, is_closed)
        e = e.next  # type: ignore

    def add_bounds_to_lml(self, e: TEdge, closed: bool) -> TEdge:
        if e.out_idx == self.skip:
            if self.more_below(e):
                e = e.next  # type: ignore
                b = self.descend_to_min(e)
            else:
                b = None
        else:
            b = self.descend_to_min(e)
        if e.out_idx == self.skip:
            self.do_minima_lml(None, b, closed)
            append_maxima = False
            if e.bot != e.prev.bot and self.more_below(e):
                e = e.next  # type: ignore
                b = self.descend_to_min(e)
                self.do_minima_lml(b, e, closed)
                append_maxima = True
            elif self.just_before_loc_min(e):
                e = e.next  # type: ignore
        else:
            self.do_minima_lml(b, e, closed)
            append_maxima = True
        self.ascend_to_max(e, append_maxima, closed)
        if e.out_idx == self.skip and (e.top != e.prev.top):
            if self.more_above(e):
                e = e.next  # type: ignore
                self.ascend_to_max(e, False, closed)
            elif e.top == e.next.top or (self.is_horizontal(e.next) and e.top == e.next.bot):
                e = e.next  # type: ignore
        return e

    def insert_local_minima(self, new_lm: LocalMinima) -> None:
        if self.minima_list is None:
            self.minima_list = new_lm
            return
        if new_lm.y >= self.minima_list.y:
            new_lm.next = self.minima_list
            self.minima_list = new_lm
            return
        tmp = self.minima_list
        while tmp.next is not None and new_lm.y < tmp.next.y:
            tmp = tmp.next
        new_lm.next = tmp.next
        tmp.next = new_lm

    def pop_local_minima(self) -> None:
        if self.current_lm is None:
            return
        self.current_lm = self.current_lm.next

    def reverse_horizontal(self, e: TEdge) -> None:
        e.top = IntPoint(e.bot.x, e.top.y)
        e.bot = IntPoint(e.top.x, e.bot.y)

    def reset(self) -> None:
        self.current_lm = self.minima_list
        if self.current_lm is None:
            return
        lm = self.minima_list
        while lm is not None:
            e = lm.left_bound
            if e is not None:
                e.curr = e.bot
                e.side = EdgeSide.esLeft
                if e.out_idx != self.skip:
                    e.out_idx = self.unassigned
            e = lm.right_bound
            if e is not None:
                e.curr = e.bot
                e.side = EdgeSide.esRight
                if e.out_idx != self.skip:
                    e.out_idx = self.unassigned
            lm = lm.next

    def get_bounds(self) -> IntRect:
        result = IntRect()
        lm = self.minima_list
        if lm is None:
            return result
        result.left = lm.left_bound.bot.x  # type: ignore
        result.top = lm.left_bound.bot.y  # type: ignore
        result.right = lm.left_bound.bot.x  # type: ignore
        result.bottom = lm.left_bound.bot.y  # type: ignore
        while lm is not None:
            if lm.left_bound.bot.y > result.bottom:  # type: ignore
                result.bottom = lm.left_bound.bot.y  # type: ignore
            e = lm.left_bound
            while True:
                bottom_e = e
                while e.next_in_lml is not None:
                    if e.bot.x < result.left:
                        result.left = e.bot.x
                    if e.bot.x > result.right:
                        result.right = e.bot.x
                    e = e.next_in_lml
                if e.bot.x < result.left:
                    result.left = e.bot.x
                if e.bot.x > result.right:
                    result.right = e.bot.x
                if e.top.x < result.left:
                    result.left = e.top.x
                if e.top.x > result.right:
                    result.right = e.top.x
                if e.top.y < result.top:
                    result.top = e.top.y
                if bottom_e == lm.left_bound:
                    e = lm.right_bound
                else:
                    break
            lm = lm.next
        return result


class Clipper(ClipperBase):
    ioReverseSolution = 1
    ioStrictlySimple = 2
    ioPreserveCollinear = 4

    def __init__(self, init_options: int = 0) -> None:
        super().__init__()
        self.scanbeam: Optional[Scanbeam] = None
        self.active_edges: Optional[TEdge] = None
        self.sorted_edges: Optional[TEdge] = None
        self.intersect_nodes: Optional[IntersectNode] = None
        self.execute_locked = False
        self.using_polytree = False
        self.poly_outs: List[OutRec] = []
        self.joins: List[Join] = []
        self.ghost_joins: List[Join] = []
        self.reverse_solution = (init_options & self.ioReverseSolution) != 0
        self.strictly_simple = (init_options & self.ioStrictlySimple) != 0
        self.preserve_collinear = (init_options & self.ioPreserveCollinear) != 0
        self.clip_type = ClipType.ctIntersection
        self.clip_fill_type = PolyFillType.pftEvenOdd
        self.subj_fill_type = PolyFillType.pftEvenOdd

    def clear(self) -> None:
        if not self.edges:
            return
        self.dispose_all_poly_pts()
        super().clear()

    def reset(self) -> None:
        super().reset()
        self.scanbeam = None
        self.active_edges = None
        self.sorted_edges = None
        self.dispose_all_poly_pts()
        lm = self.minima_list
        while lm is not None:
            self.insert_scanbeam(lm.y)
            lm = lm.next

    def insert_scanbeam(self, y: int) -> None:
        if self.scanbeam is None:
            self.scanbeam = Scanbeam(y)
            return
        if y > self.scanbeam.y:
            new_sb = Scanbeam(y)
            new_sb.next = self.scanbeam
            self.scanbeam = new_sb
            return
        sb2 = self.scanbeam
        while sb2.next is not None and y <= sb2.next.y:
            sb2 = sb2.next
        if y == sb2.y:
            return
        new_sb = Scanbeam(y)
        new_sb.next = sb2.next
        sb2.next = new_sb

    def execute(self, clip_type: int, solution: List[List[IntPoint]], subj_fill: int = PolyFillType.pftEvenOdd, clip_fill: int = PolyFillType.pftEvenOdd) -> bool:
        if self.execute_locked:
            return False
        self.execute_locked = True
        if self.has_open_paths:
            raise ClipperException("Error: PolyTree struct is needed for open path clipping.")
        solution.clear()
        self.subj_fill_type = subj_fill
        self.clip_fill_type = clip_fill
        self.clip_type = clip_type
        self.using_polytree = False
        succeeded = self.execute_internal()
        if succeeded:
            self.build_result(solution)
        self.execute_locked = False
        return succeeded

    def execute_internal(self) -> bool:
        try:
            self.reset()
            if self.current_lm is None:
                return False
            bot_y = self.pop_scanbeam()
            while self.scanbeam is not None or self.current_lm is not None:
                self.insert_local_minima_into_ael(bot_y)
                self.ghost_joins.clear()
                self.process_horizontals(False)
                if self.scanbeam is None:
                    break
                top_y = self.pop_scanbeam()
                if not self.process_intersections(bot_y, top_y):
                    return False
                self.process_edges_at_top_of_scanbeam(top_y)
                bot_y = top_y
            for out_rec in self.poly_outs:
                if out_rec.pts is None or out_rec.is_open:
                    continue
                if (out_rec.is_hole ^ self.reverse_solution) == (self.area_outrec(out_rec) > 0):
                    self.reverse_poly_pt_links(out_rec.pts)
            self.join_common_edges()
            for out_rec in self.poly_outs:
                if out_rec.pts is not None and not out_rec.is_open:
                    self.fixup_out_polygon(out_rec)
            if self.strictly_simple:
                self.do_simple_polygons()
            return True
        finally:
            self.joins.clear()
            self.ghost_joins.clear()

    def pop_scanbeam(self) -> int:
        y = self.scanbeam.y  # type: ignore
        sb2 = self.scanbeam
        self.scanbeam = self.scanbeam.next  # type: ignore
        sb2 = None
        return y

    def dispose_all_poly_pts(self) -> None:
        for i in range(len(self.poly_outs)):
            self.dispose_out_rec(i)
        self.poly_outs.clear()

    def dispose_out_rec(self, index: int) -> None:
        out_rec = self.poly_outs[index]
        if out_rec.pts is not None:
            self.dispose_out_pts(out_rec.pts)
        self.poly_outs[index] = None  # type: ignore

    def dispose_out_pts(self, pp: OutPt) -> None:
        if pp is None:
            return
        pp.prev.next = None  # type: ignore
        while pp is not None:
            tmp = pp
            pp = pp.next
            tmp = None

    def add_join(self, op1: OutPt, op2: OutPt, off_pt: IntPoint) -> None:
        j = Join()
        j.out_pt1 = op1
        j.out_pt2 = op2
        j.off_pt = off_pt
        self.joins.append(j)

    def add_ghost_join(self, op: OutPt, off_pt: IntPoint) -> None:
        j = Join()
        j.out_pt1 = op
        j.off_pt = off_pt
        self.ghost_joins.append(j)

    def insert_local_minima_into_ael(self, bot_y: int) -> None:
        while self.current_lm is not None and self.current_lm.y == bot_y:
            lb = self.current_lm.left_bound
            rb = self.current_lm.right_bound
            self.pop_local_minima()
            op1 = None
            if lb is None:
                self.insert_edge_into_ael(rb, None)
                self.set_winding_count(rb)
                if self.is_contributing(rb):
                    op1 = self.add_out_pt(rb, rb.bot)
            else:
                self.insert_edge_into_ael(lb, None)
                self.insert_edge_into_ael(rb, lb)
                self.set_winding_count(lb)
                rb.wind_cnt = lb.wind_cnt
                rb.wind_cnt2 = lb.wind_cnt2
                if self.is_contributing(lb):
                    op1 = self.add_local_min_poly(lb, rb, lb.bot)
                self.insert_scanbeam(lb.top.y)
            if self.is_horizontal(rb):
                self.add_edge_to_sel(rb)
            else:
                self.insert_scanbeam(rb.top.y)
            if lb is None:
                continue
            if op1 is not None and self.is_horizontal(rb) and self.ghost_joins and rb.wind_delta != 0:
                for j in self.ghost_joins:
                    if self.horz_segments_overlap(j.out_pt1.pt, j.off_pt, rb.bot, rb.top):
                        self.add_join(j.out_pt1, op1, j.off_pt)
            if lb.out_idx >= 0 and lb.prev_in_ael is not None and lb.prev_in_ael.curr.x == lb.bot.x and lb.prev_in_ael.out_idx >= 0 and self.slopes_equal(lb.prev_in_ael, lb) and lb.wind_delta != 0 and lb.prev_in_ael.wind_delta != 0:
                op2 = self.add_out_pt(lb.prev_in_ael, lb.bot)
                self.add_join(op1, op2, lb.top)
            if lb.next_in_ael != rb:
                if rb.out_idx >= 0 and rb.prev_in_ael.out_idx >= 0 and self.slopes_equal(rb.prev_in_ael, rb) and rb.wind_delta != 0 and rb.prev_in_ael.wind_delta != 0:
                    op2 = self.add_out_pt(rb.prev_in_ael, rb.bot)
                    self.add_join(op1, op2, rb.top)
                e = lb.next_in_ael
                while e is not None and e != rb:
                    self.intersect_edges(rb, e, lb.curr)
                    e = e.next_in_ael

    def insert_edge_into_ael(self, edge: TEdge, start_edge: Optional[TEdge]) -> None:
        if self.active_edges is None:
            edge.prev_in_ael = None
            edge.next_in_ael = None
            self.active_edges = edge
            return
        if start_edge is None and self.e2_inserts_before_e1(self.active_edges, edge):
            edge.prev_in_ael = None
            edge.next_in_ael = self.active_edges
            self.active_edges.prev_in_ael = edge
            self.active_edges = edge
            return
        if start_edge is None:
            start_edge = self.active_edges
        while start_edge.next_in_ael is not None and not self.e2_inserts_before_e1(start_edge.next_in_ael, edge):
            start_edge = start_edge.next_in_ael
        edge.next_in_ael = start_edge.next_in_ael
        if start_edge.next_in_ael is not None:
            start_edge.next_in_ael.prev_in_ael = edge
        edge.prev_in_ael = start_edge
        start_edge.next_in_ael = edge

    def e2_inserts_before_e1(self, e1: TEdge, e2: TEdge) -> bool:
        if e2.curr.x == e1.curr.x:
            if e2.top.y > e1.top.y:
                return e2.top.x < self.top_x(e1, e2.top.y)
            return e1.top.x > self.top_x(e2, e1.top.y)
        return e2.curr.x < e1.curr.x

    def is_even_odd_fill_type(self, edge: TEdge) -> bool:
        if edge.poly_typ == PolyType.ptSubject:
            return self.subj_fill_type == PolyFillType.pftEvenOdd
        return self.clip_fill_type == PolyFillType.pftEvenOdd

    def is_even_odd_alt_fill_type(self, edge: TEdge) -> bool:
        if edge.poly_typ == PolyType.ptSubject:
            return self.clip_fill_type == PolyFillType.pftEvenOdd
        return self.subj_fill_type == PolyFillType.pftEvenOdd

    def is_contributing(self, edge: TEdge) -> bool:
        if edge.poly_typ == PolyType.ptSubject:
            pft = self.subj_fill_type
            pft2 = self.clip_fill_type
        else:
            pft = self.clip_fill_type
            pft2 = self.subj_fill_type
        if pft == PolyFillType.pftEvenOdd:
            if edge.wind_delta == 0 and edge.wind_cnt != 1:
                return False
        elif pft == PolyFillType.pftNonZero:
            if abs(edge.wind_cnt) != 1:
                return False
        elif pft == PolyFillType.pftPositive:
            if edge.wind_cnt != 1:
                return False
        else:
            if edge.wind_cnt != -1:
                return False
        if self.clip_type == ClipType.ctIntersection:
            if pft2 in (PolyFillType.pftEvenOdd, PolyFillType.pftNonZero):
                return edge.wind_cnt2 != 0
            if pft2 == PolyFillType.pftPositive:
                return edge.wind_cnt2 > 0
            return edge.wind_cnt2 < 0
        if self.clip_type == ClipType.ctUnion:
            if pft2 in (PolyFillType.pftEvenOdd, PolyFillType.pftNonZero):
                return edge.wind_cnt2 == 0
            if pft2 == PolyFillType.pftPositive:
                return edge.wind_cnt2 <= 0
            return edge.wind_cnt2 >= 0
        if self.clip_type == ClipType.ctDifference:
            if edge.poly_typ == PolyType.ptSubject:
                if pft2 in (PolyFillType.pftEvenOdd, PolyFillType.pftNonZero):
                    return edge.wind_cnt2 == 0
                if pft2 == PolyFillType.pftPositive:
                    return edge.wind_cnt2 <= 0
                return edge.wind_cnt2 >= 0
            if pft2 in (PolyFillType.pftEvenOdd, PolyFillType.pftNonZero):
                return edge.wind_cnt2 != 0
            if pft2 == PolyFillType.pftPositive:
                return edge.wind_cnt2 > 0
            return edge.wind_cnt2 < 0
        if self.clip_type == ClipType.ctXor:
            if edge.wind_delta == 0:
                if pft2 in (PolyFillType.pftEvenOdd, PolyFillType.pftNonZero):
                    return edge.wind_cnt2 == 0
                if pft2 == PolyFillType.pftPositive:
                    return edge.wind_cnt2 <= 0
                return edge.wind_cnt2 >= 0
            return True
        return True

    def set_winding_count(self, edge: TEdge) -> None:
        e = edge.prev_in_ael
        while e is not None and ((e.poly_typ != edge.poly_typ) or (e.wind_delta == 0)):
            e = e.prev_in_ael
        if e is None:
            edge.wind_cnt = 1 if edge.wind_delta == 0 else edge.wind_delta
            edge.wind_cnt2 = 0
            e = self.active_edges
        elif edge.wind_delta == 0 and self.clip_type != ClipType.ctUnion:
            edge.wind_cnt = 1
            edge.wind_cnt2 = e.wind_cnt2
            e = e.next_in_ael
        elif self.is_even_odd_fill_type(edge):
            if edge.wind_delta == 0:
                inside = True
                e2 = e.prev_in_ael
                while e2 is not None:
                    if e2.poly_typ == e.poly_typ and e2.wind_delta != 0:
                        inside = not inside
                    e2 = e2.prev_in_ael
                edge.wind_cnt = 0 if inside else 1
            else:
                edge.wind_cnt = edge.wind_delta
            edge.wind_cnt2 = e.wind_cnt2
            e = e.next_in_ael
        else:
            if e.wind_cnt * e.wind_delta < 0:
                if abs(e.wind_cnt) > 1:
                    if e.wind_delta * edge.wind_delta < 0:
                        edge.wind_cnt = e.wind_cnt
                    else:
                        edge.wind_cnt = e.wind_cnt + edge.wind_delta
                else:
                    edge.wind_cnt = 1 if edge.wind_delta == 0 else edge.wind_delta
            else:
                if edge.wind_delta == 0:
                    edge.wind_cnt = e.wind_cnt - 1 if e.wind_cnt < 0 else e.wind_cnt + 1
                elif e.wind_delta * edge.wind_delta < 0:
                    edge.wind_cnt = e.wind_cnt
                else:
                    edge.wind_cnt = e.wind_cnt + edge.wind_delta
            edge.wind_cnt2 = e.wind_cnt2
            e = e.next_in_ael
        if self.is_even_odd_alt_fill_type(edge):
            while e is not edge:
                if e.wind_delta != 0:
                    edge.wind_cnt2 = 0 if edge.wind_cnt2 else 1
                e = e.next_in_ael
        else:
            while e is not edge:
                edge.wind_cnt2 += e.wind_delta
                e = e.next_in_ael

    def add_edge_to_sel(self, edge: TEdge) -> None:
        if self.sorted_edges is None:
            self.sorted_edges = edge
            edge.prev_in_sel = None
            edge.next_in_sel = None
        else:
            edge.next_in_sel = self.sorted_edges
            edge.prev_in_sel = None
            self.sorted_edges.prev_in_sel = edge
            self.sorted_edges = edge

    def copy_ael_to_sel(self) -> None:
        e = self.active_edges
        self.sorted_edges = e
        while e is not None:
            e.prev_in_sel = e.prev_in_ael
            e.next_in_sel = e.next_in_ael
            e = e.next_in_ael

    def swap_positions_in_ael(self, edge1: TEdge, edge2: TEdge) -> None:
        if edge1.next_in_ael == edge1.prev_in_ael or edge2.next_in_ael == edge2.prev_in_ael:
            return
        if edge1.next_in_ael == edge2:
            nxt = edge2.next_in_ael
            if nxt is not None:
                nxt.prev_in_ael = edge1
            prev = edge1.prev_in_ael
            if prev is not None:
                prev.next_in_ael = edge2
            edge2.prev_in_ael = prev
            edge2.next_in_ael = edge1
            edge1.prev_in_ael = edge2
            edge1.next_in_ael = nxt
        elif edge2.next_in_ael == edge1:
            nxt = edge1.next_in_ael
            if nxt is not None:
                nxt.prev_in_ael = edge2
            prev = edge2.prev_in_ael
            if prev is not None:
                prev.next_in_ael = edge1
            edge1.prev_in_ael = prev
            edge1.next_in_ael = edge2
            edge2.prev_in_ael = edge1
            edge2.next_in_ael = nxt
        else:
            nxt = edge1.next_in_ael
            prev = edge1.prev_in_ael
            edge1.next_in_ael = edge2.next_in_ael
            if edge1.next_in_ael is not None:
                edge1.next_in_ael.prev_in_ael = edge1
            edge1.prev_in_ael = edge2.prev_in_ael
            if edge1.prev_in_ael is not None:
                edge1.prev_in_ael.next_in_ael = edge1
            edge2.next_in_ael = nxt
            if edge2.next_in_ael is not None:
                edge2.next_in_ael.prev_in_ael = edge2
            edge2.prev_in_ael = prev
            if edge2.prev_in_ael is not None:
                edge2.prev_in_ael.next_in_ael = edge2
        if edge1.prev_in_ael is None:
            self.active_edges = edge1
        elif edge2.prev_in_ael is None:
            self.active_edges = edge2

    def swap_positions_in_sel(self, edge1: TEdge, edge2: TEdge) -> None:
        if (edge1.next_in_sel is None and edge1.prev_in_sel is None) or (
            edge2.next_in_sel is None and edge2.prev_in_sel is None
        ):
            return
        if edge1.next_in_sel == edge2:
            nxt = edge2.next_in_sel
            if nxt is not None:
                nxt.prev_in_sel = edge1
            prev = edge1.prev_in_sel
            if prev is not None:
                prev.next_in_sel = edge2
            edge2.prev_in_sel = prev
            edge2.next_in_sel = edge1
            edge1.prev_in_sel = edge2
            edge1.next_in_sel = nxt
        elif edge2.next_in_sel == edge1:
            nxt = edge1.next_in_sel
            if nxt is not None:
                nxt.prev_in_sel = edge2
            prev = edge2.prev_in_sel
            if prev is not None:
                prev.next_in_sel = edge1
            edge1.prev_in_sel = prev
            edge1.next_in_sel = edge2
            edge2.prev_in_sel = edge1
            edge2.next_in_sel = nxt
        else:
            nxt = edge1.next_in_sel
            prev = edge1.prev_in_sel
            edge1.next_in_sel = edge2.next_in_sel
            if edge1.next_in_sel is not None:
                edge1.next_in_sel.prev_in_sel = edge1
            edge1.prev_in_sel = edge2.prev_in_sel
            if edge1.prev_in_sel is not None:
                edge1.prev_in_sel.next_in_sel = edge1
            edge2.next_in_sel = nxt
            if edge2.next_in_sel is not None:
                edge2.next_in_sel.prev_in_sel = edge2
            edge2.prev_in_sel = prev
            if edge2.prev_in_sel is not None:
                edge2.prev_in_sel.next_in_sel = edge2
        if edge1.prev_in_sel is None:
            self.sorted_edges = edge1
        elif edge2.prev_in_sel is None:
            self.sorted_edges = edge2

    def add_local_max_poly(self, e1: TEdge, e2: TEdge, pt: IntPoint) -> None:
        self.add_out_pt(e1, pt)
        if e1.out_idx == e2.out_idx:
            e1.out_idx = self.unassigned
            e2.out_idx = self.unassigned
        elif e1.out_idx < e2.out_idx:
            self.append_polygon(e1, e2)
        else:
            self.append_polygon(e2, e1)

    def add_local_min_poly(self, e1: TEdge, e2: TEdge, pt: IntPoint) -> OutPt:
        if self.is_horizontal(e2) or (e1.dx > e2.dx):
            result = self.add_out_pt(e1, pt)
            e2.out_idx = e1.out_idx
            e1.side = EdgeSide.esLeft
            e2.side = EdgeSide.esRight
            e = e1
            prev_e = e2.prev_in_ael if e.prev_in_ael == e2 else e.prev_in_ael
        else:
            result = self.add_out_pt(e2, pt)
            e1.out_idx = e2.out_idx
            e1.side = EdgeSide.esRight
            e2.side = EdgeSide.esLeft
            e = e2
            prev_e = e1.prev_in_ael if e.prev_in_ael == e1 else e.prev_in_ael
        if prev_e is not None and prev_e.out_idx >= 0 and self.top_x(prev_e, pt.y) == self.top_x(e, pt.y) and self.slopes_equal(e, prev_e) and e.wind_delta != 0 and prev_e.wind_delta != 0:
            out_pt = self.add_out_pt(prev_e, pt)
            self.add_join(result, out_pt, e.top)
        return result

    def create_out_rec(self) -> OutRec:
        result = OutRec()
        self.poly_outs.append(result)
        result.idx = len(self.poly_outs) - 1
        return result

    def add_out_pt(self, e: TEdge, pt: IntPoint) -> OutPt:
        to_front = e.side == EdgeSide.esLeft
        if e.out_idx < 0:
            out_rec = self.create_out_rec()
            out_rec.is_open = e.wind_delta == 0
            new_op = OutPt()
            out_rec.pts = new_op
            new_op.idx = out_rec.idx
            new_op.pt = pt
            new_op.next = new_op
            new_op.prev = new_op
            if not out_rec.is_open:
                self.set_hole_state(e, out_rec)
            e.out_idx = out_rec.idx
            return new_op
        out_rec = self.poly_outs[e.out_idx]
        op = out_rec.pts
        if to_front and pt == op.pt:  # type: ignore
            return op
        if not to_front and pt == op.prev.pt:  # type: ignore
            return op.prev  # type: ignore
        new_op = OutPt()
        new_op.idx = out_rec.idx
        new_op.pt = pt
        new_op.next = op
        new_op.prev = op.prev  # type: ignore
        new_op.prev.next = new_op  # type: ignore
        op.prev = new_op  # type: ignore
        if to_front:
            out_rec.pts = new_op
        return new_op

    def swap_points(self, pt1: IntPoint, pt2: IntPoint) -> tuple[IntPoint, IntPoint]:
        return pt2, pt1

    def horz_segments_overlap(self, pt1a: IntPoint, pt1b: IntPoint, pt2a: IntPoint, pt2b: IntPoint) -> bool:
        if (pt1a.x > pt2a.x) == (pt1a.x < pt2b.x):
            return True
        if (pt1b.x > pt2a.x) == (pt1b.x < pt2b.x):
            return True
        if (pt2a.x > pt1a.x) == (pt2a.x < pt1b.x):
            return True
        if (pt2b.x > pt1a.x) == (pt2b.x < pt1b.x):
            return True
        if pt1a.x == pt2a.x and pt1b.x == pt2b.x:
            return True
        if pt1a.x == pt2b.x and pt1b.x == pt2a.x:
            return True
        return False

    def insert_poly_pt_between(self, p1: OutPt, p2: OutPt, pt: IntPoint) -> OutPt:
        result = OutPt()
        result.pt = pt
        if p2 == p1.next:
            p1.next = result
            p2.prev = result
            result.next = p2
            result.prev = p1
        else:
            p2.next = result
            p1.prev = result
            result.next = p1
            result.prev = p2
        return result

    def set_hole_state(self, e: TEdge, out_rec: OutRec) -> None:
        is_hole = False
        e2 = e.prev_in_ael
        while e2 is not None:
            if e2.out_idx >= 0:
                is_hole = not is_hole
                if out_rec.first_left is None:
                    out_rec.first_left = self.poly_outs[e2.out_idx]
            e2 = e2.prev_in_ael
        out_rec.is_hole = is_hole

    def get_dx(self, pt1: IntPoint, pt2: IntPoint) -> float:
        if pt1.y == pt2.y:
            return self.horizontal
        return (pt2.x - pt1.x) / (pt2.y - pt1.y)

    def first_is_bottom_pt(self, btm_pt1: OutPt, btm_pt2: OutPt) -> bool:
        p = btm_pt1.prev
        while p.pt == btm_pt1.pt and p != btm_pt1:
            p = p.prev
        dx1p = abs(self.get_dx(btm_pt1.pt, p.pt))
        p = btm_pt1.next
        while p.pt == btm_pt1.pt and p != btm_pt1:
            p = p.next
        dx1n = abs(self.get_dx(btm_pt1.pt, p.pt))
        p = btm_pt2.prev
        while p.pt == btm_pt2.pt and p != btm_pt2:
            p = p.prev
        dx2p = abs(self.get_dx(btm_pt2.pt, p.pt))
        p = btm_pt2.next
        while p.pt == btm_pt2.pt and p != btm_pt2:
            p = p.next
        dx2n = abs(self.get_dx(btm_pt2.pt, p.pt))
        return (dx1p >= dx2p and dx1p >= dx2n) or (dx1n >= dx2p and dx1n >= dx2n)

    def get_bottom_pt(self, pp: OutPt) -> OutPt:
        dups = None
        p = pp.next
        while p != pp:
            if p.pt.y > pp.pt.y:
                pp = p
                dups = None
            elif p.pt.y == pp.pt.y and p.pt.x <= pp.pt.x:
                if p.pt.x < pp.pt.x:
                    dups = None
                    pp = p
                elif p.next != pp and p.prev != pp:
                    dups = p
            p = p.next
        if dups is not None:
            while dups != p:
                if not self.first_is_bottom_pt(p, dups):
                    pp = dups
                dups = dups.next
                while dups.pt != pp.pt:
                    dups = dups.next
        return pp

    def get_lowermost_rec(self, out_rec1: OutRec, out_rec2: OutRec) -> OutRec:
        if out_rec1.bottom_pt is None:
            out_rec1.bottom_pt = self.get_bottom_pt(out_rec1.pts)
        if out_rec2.bottom_pt is None:
            out_rec2.bottom_pt = self.get_bottom_pt(out_rec2.pts)
        b1 = out_rec1.bottom_pt
        b2 = out_rec2.bottom_pt
        if b1.pt.y > b2.pt.y:
            return out_rec1
        if b1.pt.y < b2.pt.y:
            return out_rec2
        if b1.pt.x < b2.pt.x:
            return out_rec1
        if b1.pt.x > b2.pt.x:
            return out_rec2
        if b1.next == b1:
            return out_rec2
        if b2.next == b2:
            return out_rec1
        if self.first_is_bottom_pt(b1, b2):
            return out_rec1
        return out_rec2

    def param1_right_of_param2(self, out_rec1: OutRec, out_rec2: OutRec) -> bool:
        while out_rec1 is not None:
            out_rec1 = out_rec1.first_left
            if out_rec1 == out_rec2:
                return True
        return False

    def get_out_rec(self, idx: int) -> OutRec:
        out_rec = self.poly_outs[idx]
        while out_rec != self.poly_outs[out_rec.idx]:
            out_rec = self.poly_outs[out_rec.idx]
        return out_rec

    def append_polygon(self, e1: TEdge, e2: TEdge) -> None:
        out_rec1 = self.poly_outs[e1.out_idx]
        out_rec2 = self.poly_outs[e2.out_idx]
        if self.param1_right_of_param2(out_rec1, out_rec2):
            hole_state_rec = out_rec2
        elif self.param1_right_of_param2(out_rec2, out_rec1):
            hole_state_rec = out_rec1
        else:
            hole_state_rec = self.get_lowermost_rec(out_rec1, out_rec2)
        p1_lft = out_rec1.pts
        p1_rt = p1_lft.prev
        p2_lft = out_rec2.pts
        p2_rt = p2_lft.prev
        if e1.side == EdgeSide.esLeft:
            if e2.side == EdgeSide.esLeft:
                self.reverse_poly_pt_links(p2_lft)
                p2_lft.next = p1_lft
                p1_lft.prev = p2_lft
                p1_rt.next = p2_rt
                p2_rt.prev = p1_rt
                out_rec1.pts = p2_rt
            else:
                p2_rt.next = p1_lft
                p1_lft.prev = p2_rt
                p2_lft.prev = p1_rt
                p1_rt.next = p2_lft
                out_rec1.pts = p2_lft
            side = EdgeSide.esLeft
        else:
            if e2.side == EdgeSide.esRight:
                self.reverse_poly_pt_links(p2_lft)
                p1_rt.next = p2_rt
                p2_rt.prev = p1_rt
                p2_lft.next = p1_lft
                p1_lft.prev = p2_lft
            else:
                p1_rt.next = p2_lft
                p2_lft.prev = p1_rt
                p1_lft.prev = p2_rt
                p2_rt.next = p1_lft
            side = EdgeSide.esRight
        out_rec1.bottom_pt = None
        if hole_state_rec == out_rec2:
            if out_rec2.first_left != out_rec1:
                out_rec1.first_left = out_rec2.first_left
            out_rec1.is_hole = out_rec2.is_hole
        out_rec2.pts = None
        out_rec2.bottom_pt = None
        out_rec2.first_left = out_rec1
        ok_idx = e1.out_idx
        obsolete_idx = e2.out_idx
        e1.out_idx = self.unassigned
        e2.out_idx = self.unassigned
        e = self.active_edges
        while e is not None:
            if e.out_idx == obsolete_idx:
                e.out_idx = ok_idx
                e.side = side
                break
            e = e.next_in_ael
        out_rec2.idx = out_rec1.idx

    def reverse_poly_pt_links(self, pp: OutPt) -> None:
        if pp is None:
            return
        pp1 = pp
        while True:
            pp2 = pp1.next
            pp1.next = pp1.prev
            pp1.prev = pp2
            pp1 = pp2
            if pp1 == pp:
                break

    def swap_sides(self, edge1: TEdge, edge2: TEdge) -> None:
        edge1.side, edge2.side = edge2.side, edge1.side

    def swap_poly_indexes(self, edge1: TEdge, edge2: TEdge) -> None:
        edge1.out_idx, edge2.out_idx = edge2.out_idx, edge1.out_idx

    def intersect_edges(self, e1: TEdge, e2: TEdge, pt: IntPoint, protect: bool = False) -> None:
        e1stops = not protect and e1.next_in_lml is None and e1.top.x == pt.x and e1.top.y == pt.y
        e2stops = not protect and e2.next_in_lml is None and e2.top.x == pt.x and e2.top.y == pt.y
        e1_contrib = e1.out_idx >= 0
        e2_contrib = e2.out_idx >= 0
        if e1.poly_typ == e2.poly_typ:
            if self.is_even_odd_fill_type(e1):
                e1.wind_cnt, e2.wind_cnt = e2.wind_cnt, e1.wind_cnt
            else:
                if e1.wind_cnt + e2.wind_delta == 0:
                    e1.wind_cnt = -e1.wind_cnt
                else:
                    e1.wind_cnt += e2.wind_delta
                if e2.wind_cnt - e1.wind_delta == 0:
                    e2.wind_cnt = -e2.wind_cnt
                else:
                    e2.wind_cnt -= e1.wind_delta
        else:
            if not self.is_even_odd_fill_type(e2):
                e1.wind_cnt2 += e2.wind_delta
            else:
                e1.wind_cnt2 = 0 if e1.wind_cnt2 else 1
            if not self.is_even_odd_fill_type(e1):
                e2.wind_cnt2 -= e1.wind_delta
            else:
                e2.wind_cnt2 = 0 if e2.wind_cnt2 else 1
        if e1.poly_typ == PolyType.ptSubject:
            e1_fill_type = self.subj_fill_type
            e1_fill_type2 = self.clip_fill_type
        else:
            e1_fill_type = self.clip_fill_type
            e1_fill_type2 = self.subj_fill_type
        if e2.poly_typ == PolyType.ptSubject:
            e2_fill_type = self.subj_fill_type
            e2_fill_type2 = self.clip_fill_type
        else:
            e2_fill_type = self.clip_fill_type
            e2_fill_type2 = self.subj_fill_type
        e1_wc = e1.wind_cnt if e1_fill_type == PolyFillType.pftPositive else (-e1.wind_cnt if e1_fill_type == PolyFillType.pftNegative else abs(e1.wind_cnt))
        e2_wc = e2.wind_cnt if e2_fill_type == PolyFillType.pftPositive else (-e2.wind_cnt if e2_fill_type == PolyFillType.pftNegative else abs(e2.wind_cnt))
        if e1_contrib and e2_contrib:
            if e1stops or e2stops or (e1_wc not in (0, 1)) or (e2_wc not in (0, 1)) or (e1.poly_typ != e2.poly_typ and self.clip_type != ClipType.ctXor):
                self.add_local_max_poly(e1, e2, pt)
            else:
                self.add_out_pt(e1, pt)
                self.add_out_pt(e2, pt)
                self.swap_sides(e1, e2)
                self.swap_poly_indexes(e1, e2)
        elif e1_contrib:
            if e2_wc in (0, 1):
                self.add_out_pt(e1, pt)
                self.swap_sides(e1, e2)
                self.swap_poly_indexes(e1, e2)
        elif e2_contrib:
            if e1_wc in (0, 1):
                self.add_out_pt(e2, pt)
                self.swap_sides(e1, e2)
                self.swap_poly_indexes(e1, e2)
        elif e1_wc in (0, 1) and e2_wc in (0, 1) and not e1stops and not e2stops:
            e1_wc2 = e1.wind_cnt2 if e1_fill_type2 == PolyFillType.pftPositive else (-e1.wind_cnt2 if e1_fill_type2 == PolyFillType.pftNegative else abs(e1.wind_cnt2))
            e2_wc2 = e2.wind_cnt2 if e2_fill_type2 == PolyFillType.pftPositive else (-e2.wind_cnt2 if e2_fill_type2 == PolyFillType.pftNegative else abs(e2.wind_cnt2))
            if e1.poly_typ != e2.poly_typ:
                self.add_local_min_poly(e1, e2, pt)
            elif e1_wc == 1 and e2_wc == 1:
                if self.clip_type == ClipType.ctIntersection:
                    if e1_wc2 > 0 and e2_wc2 > 0:
                        self.add_local_min_poly(e1, e2, pt)
                elif self.clip_type == ClipType.ctUnion:
                    if e1_wc2 <= 0 and e2_wc2 <= 0:
                        self.add_local_min_poly(e1, e2, pt)
                elif self.clip_type == ClipType.ctDifference:
                    if (e1.poly_typ == PolyType.ptClip and e1_wc2 > 0 and e2_wc2 > 0) or (
                        e1.poly_typ == PolyType.ptSubject and e1_wc2 <= 0 and e2_wc2 <= 0
                    ):
                        self.add_local_min_poly(e1, e2, pt)
                else:
                    self.add_local_min_poly(e1, e2, pt)
            else:
                self.swap_sides(e1, e2)
        if (e1stops != e2stops) and ((e1stops and e1.out_idx >= 0) or (e2stops and e2.out_idx >= 0)):
            self.swap_sides(e1, e2)
            self.swap_poly_indexes(e1, e2)
        if e1stops:
            self.delete_from_ael(e1)
        if e2stops:
            self.delete_from_ael(e2)

    def delete_from_ael(self, e: TEdge) -> None:
        prev = e.prev_in_ael
        nxt = e.next_in_ael
        if prev is None and nxt is None and e != self.active_edges:
            return
        if prev is not None:
            prev.next_in_ael = nxt
        else:
            self.active_edges = nxt
        if nxt is not None:
            nxt.prev_in_ael = prev
        e.next_in_ael = None
        e.prev_in_ael = None

    def delete_from_sel(self, e: TEdge) -> None:
        prev = e.prev_in_sel
        nxt = e.next_in_sel
        if prev is None and nxt is None and e != self.sorted_edges:
            return
        if prev is not None:
            prev.next_in_sel = nxt
        else:
            self.sorted_edges = nxt
        if nxt is not None:
            nxt.prev_in_sel = prev
        e.next_in_sel = None
        e.prev_in_sel = None

    def update_edge_into_ael(self, e: TEdge) -> TEdge:
        if e.next_in_lml is None:
            raise ClipperException("UpdateEdgeIntoAEL: invalid call")
        prev = e.prev_in_ael
        nxt = e.next_in_ael
        e.next_in_lml.out_idx = e.out_idx
        if prev is not None:
            prev.next_in_ael = e.next_in_lml
        else:
            self.active_edges = e.next_in_lml
        if nxt is not None:
            nxt.prev_in_ael = e.next_in_lml
        e.next_in_lml.side = e.side
        e.next_in_lml.wind_delta = e.wind_delta
        e.next_in_lml.wind_cnt = e.wind_cnt
        e.next_in_lml.wind_cnt2 = e.wind_cnt2
        e = e.next_in_lml
        e.curr = e.bot
        e.prev_in_ael = prev
        e.next_in_ael = nxt
        if not self.is_horizontal(e):
            self.insert_scanbeam(e.top.y)
        return e

    def process_horizontals(self, is_top_of_scanbeam: bool) -> None:
        horz_edge = self.sorted_edges
        while horz_edge is not None:
            self.delete_from_sel(horz_edge)
            self.process_horizontal(horz_edge, is_top_of_scanbeam)
            horz_edge = self.sorted_edges

    def get_horz_direction(self, horz_edge: TEdge) -> tuple[int, int, int]:
        if horz_edge.bot.x < horz_edge.top.x:
            left = horz_edge.bot.x
            right = horz_edge.top.x
            direction = Direction.dLeftToRight
        else:
            left = horz_edge.top.x
            right = horz_edge.bot.x
            direction = Direction.dRightToLeft
        return direction, left, right

    def prepare_horz_joins(self, horz_edge: TEdge, is_top_of_scanbeam: bool) -> None:
        out_pt = self.poly_outs[horz_edge.out_idx].pts
        if horz_edge.side != EdgeSide.esLeft:
            out_pt = out_pt.prev
        for j in self.ghost_joins:
            if self.horz_segments_overlap(j.out_pt1.pt, j.off_pt, horz_edge.bot, horz_edge.top):
                self.add_join(j.out_pt1, out_pt, j.off_pt)
        if is_top_of_scanbeam:
            if out_pt.pt == horz_edge.top:
                self.add_ghost_join(out_pt, horz_edge.bot)
            else:
                self.add_ghost_join(out_pt, horz_edge.top)

    def process_horizontal(self, horz_edge: TEdge, is_top_of_scanbeam: bool) -> None:
        direction, horz_left, horz_right = self.get_horz_direction(horz_edge)
        e_last_horz = horz_edge
        while e_last_horz.next_in_lml is not None and self.is_horizontal(e_last_horz.next_in_lml):
            e_last_horz = e_last_horz.next_in_lml
        e_max_pair = None
        if e_last_horz.next_in_lml is None:
            e_max_pair = self.get_maxima_pair(e_last_horz)
        while True:
            is_last_horz = horz_edge == e_last_horz
            e = self.get_next_in_ael(horz_edge, direction)
            while e is not None:
                if e.curr.x == horz_edge.top.x and horz_edge.next_in_lml is not None and e.dx < horz_edge.next_in_lml.dx:
                    break
                e_next = self.get_next_in_ael(e, direction)
                if (direction == Direction.dLeftToRight and e.curr.x <= horz_right) or (
                    direction == Direction.dRightToLeft and e.curr.x >= horz_left
                ):
                    if e == e_max_pair and is_last_horz:
                        if horz_edge.out_idx >= 0 and horz_edge.wind_delta != 0:
                            self.prepare_horz_joins(horz_edge, is_top_of_scanbeam)
                        if direction == Direction.dLeftToRight:
                            self.intersect_edges(horz_edge, e, e.top)
                        else:
                            self.intersect_edges(e, horz_edge, e.top)
                        if e_max_pair.out_idx >= 0:
                            raise ClipperException("ProcessHorizontal error")
                        return
                    if direction == Direction.dLeftToRight:
                        pt = IntPoint(e.curr.x, horz_edge.curr.y)
                        self.intersect_edges(horz_edge, e, pt, True)
                    else:
                        pt = IntPoint(e.curr.x, horz_edge.curr.y)
                        self.intersect_edges(e, horz_edge, pt, True)
                    self.swap_positions_in_ael(horz_edge, e)
                elif (direction == Direction.dLeftToRight and e.curr.x >= horz_right) or (
                    direction == Direction.dRightToLeft and e.curr.x <= horz_left
                ):
                    break
                e = e_next
            if horz_edge.out_idx >= 0 and horz_edge.wind_delta != 0:
                self.prepare_horz_joins(horz_edge, is_top_of_scanbeam)
            if horz_edge.next_in_lml is not None and self.is_horizontal(horz_edge.next_in_lml):
                horz_edge = self.update_edge_into_ael(horz_edge)
                if horz_edge.out_idx >= 0:
                    self.add_out_pt(horz_edge, horz_edge.bot)
                direction, horz_left, horz_right = self.get_horz_direction(horz_edge)
            else:
                break
        if horz_edge.next_in_lml is not None:
            if horz_edge.out_idx >= 0:
                op1 = self.add_out_pt(horz_edge, horz_edge.top)
                horz_edge = self.update_edge_into_ael(horz_edge)
                if horz_edge.wind_delta == 0:
                    return
                e_prev = horz_edge.prev_in_ael
                e_next = horz_edge.next_in_ael
                if e_prev is not None and e_prev.curr.x == horz_edge.bot.x and e_prev.curr.y == horz_edge.bot.y and e_prev.wind_delta != 0 and e_prev.out_idx >= 0 and e_prev.curr.y > e_prev.top.y and self.slopes_equal(horz_edge, e_prev):
                    op2 = self.add_out_pt(e_prev, horz_edge.bot)
                    self.add_join(op1, op2, horz_edge.top)
                elif e_next is not None and e_next.curr.x == horz_edge.bot.x and e_next.curr.y == horz_edge.bot.y and e_next.wind_delta != 0 and e_next.out_idx >= 0 and e_next.curr.y > e_next.top.y and self.slopes_equal(horz_edge, e_next):
                    op2 = self.add_out_pt(e_next, horz_edge.bot)
                    self.add_join(op1, op2, horz_edge.top)
            else:
                horz_edge = self.update_edge_into_ael(horz_edge)
        elif e_max_pair is not None:
            if e_max_pair.out_idx >= 0:
                if direction == Direction.dLeftToRight:
                    self.intersect_edges(horz_edge, e_max_pair, horz_edge.top)
                else:
                    self.intersect_edges(e_max_pair, horz_edge, horz_edge.top)
                if e_max_pair.out_idx >= 0:
                    raise ClipperException("ProcessHorizontal error")
            else:
                self.delete_from_ael(horz_edge)
                self.delete_from_ael(e_max_pair)
        else:
            if horz_edge.out_idx >= 0:
                self.add_out_pt(horz_edge, horz_edge.top)
            self.delete_from_ael(horz_edge)

    def get_next_in_ael(self, e: TEdge, direction: int) -> Optional[TEdge]:
        return e.next_in_ael if direction == Direction.dLeftToRight else e.prev_in_ael

    def is_minima(self, e: TEdge) -> bool:
        return e is not None and (e.prev.next_in_lml != e) and (e.next.next_in_lml != e)

    def is_maxima(self, e: TEdge, y: float) -> bool:
        return e is not None and e.top.y == y and e.next_in_lml is None

    def is_intermediate(self, e: TEdge, y: float) -> bool:
        return e.top.y == y and e.next_in_lml is not None

    def get_maxima_pair(self, e: TEdge) -> Optional[TEdge]:
        result = None
        if e.next.top == e.top and e.next.next_in_lml is None:
            result = e.next
        elif e.prev.top == e.top and e.prev.next_in_lml is None:
            result = e.prev
        if result is not None and (result.out_idx == self.skip or (result.next_in_ael == result.prev_in_ael and not self.is_horizontal(result))):
            return None
        return result

    def process_intersections(self, bot_y: int, top_y: int) -> bool:
        if self.active_edges is None:
            return True
        try:
            self.build_intersect_list(bot_y, top_y)
            if self.intersect_nodes is None:
                return True
            if self.intersect_nodes.next is None or self.fixup_intersection_order():
                self.process_intersect_list()
            else:
                return False
        except Exception as exc:
            self.sorted_edges = None
            self.dispose_intersect_nodes()
            raise ClipperException("ProcessIntersections error") from exc
        self.sorted_edges = None
        return True

    def build_intersect_list(self, bot_y: int, top_y: int) -> None:
        if self.active_edges is None:
            return
        e = self.active_edges
        self.sorted_edges = e
        while e is not None:
            e.prev_in_sel = e.prev_in_ael
            e.next_in_sel = e.next_in_ael
            e.curr.x = self.top_x(e, top_y)
            e = e.next_in_ael
        is_modified = True
        while is_modified and self.sorted_edges is not None:
            is_modified = False
            e = self.sorted_edges
            while e.next_in_sel is not None:
                e_next = e.next_in_sel
                if e.curr.x > e_next.curr.x:
                    pt = IntPoint(0, 0)
                    if not self.intersect_point(e, e_next, pt) and e.curr.x > e_next.curr.x + 1:
                        raise ClipperException("Intersection error")
                    if pt.y > bot_y:
                        pt.y = bot_y
                        if abs(e.dx) > abs(e_next.dx):
                            pt.x = self.top_x(e_next, bot_y)
                        else:
                            pt.x = self.top_x(e, bot_y)
                    self.insert_intersect_node(e, e_next, pt)
                    self.swap_positions_in_sel(e, e_next)
                    is_modified = True
                else:
                    e = e_next
            if e.prev_in_sel is not None:
                e.prev_in_sel.next_in_sel = None
            else:
                break
        self.sorted_edges = None

    def edges_adjacent(self, inode: IntersectNode) -> bool:
        return inode.edge1.next_in_sel == inode.edge2 or inode.edge1.prev_in_sel == inode.edge2

    def fixup_intersection_order(self) -> bool:
        inode = self.intersect_nodes
        self.copy_ael_to_sel()
        while inode is not None:
            if not self.edges_adjacent(inode):
                next_node = inode.next
                while next_node is not None and not self.edges_adjacent(next_node):
                    next_node = next_node.next
                if next_node is None:
                    return False
                self.swap_intersect_nodes(inode, next_node)
            self.swap_positions_in_sel(inode.edge1, inode.edge2)
            inode = inode.next
        return True

    def process_intersect_list(self) -> None:
        while self.intersect_nodes is not None:
            i_node = self.intersect_nodes.next
            self.intersect_edges(self.intersect_nodes.edge1, self.intersect_nodes.edge2, self.intersect_nodes.pt, True)
            self.swap_positions_in_ael(self.intersect_nodes.edge1, self.intersect_nodes.edge2)
            self.intersect_nodes = i_node

    @staticmethod
    def round(value: float) -> int:
        return int(value - 0.5) if value < 0 else int(value + 0.5)

    def top_x(self, edge: TEdge, current_y: int) -> int:
        if current_y == edge.top.y:
            return edge.top.x
        return edge.bot.x + self.round(edge.dx * (current_y - edge.bot.y))

    def insert_intersect_node(self, e1: TEdge, e2: TEdge, pt: IntPoint) -> None:
        new_node = IntersectNode()
        new_node.edge1 = e1
        new_node.edge2 = e2
        new_node.pt = pt
        if self.intersect_nodes is None:
            self.intersect_nodes = new_node
        elif new_node.pt.y > self.intersect_nodes.pt.y:
            new_node.next = self.intersect_nodes
            self.intersect_nodes = new_node
        else:
            i_node = self.intersect_nodes
            while i_node.next is not None and new_node.pt.y < i_node.next.pt.y:
                i_node = i_node.next
            new_node.next = i_node.next
            i_node.next = new_node

    def swap_intersect_nodes(self, int1: IntersectNode, int2: IntersectNode) -> None:
        e1 = int1.edge1
        e2 = int1.edge2
        p = IntPoint(int1.pt.x, int1.pt.y)
        int1.edge1 = int2.edge1
        int1.edge2 = int2.edge2
        int1.pt = int2.pt
        int2.edge1 = e1
        int2.edge2 = e2
        int2.pt = p

    def intersect_point(self, edge1: TEdge, edge2: TEdge, ip: IntPoint) -> bool:
        if self.slopes_equal(edge1, edge2):
            ip.y = edge2.bot.y if edge2.bot.y > edge1.bot.y else edge1.bot.y
            return False
        if edge1.delta.x == 0:
            ip.x = edge1.bot.x
            if self.is_horizontal(edge2):
                ip.y = edge2.bot.y
            else:
                b2 = edge2.bot.y - (edge2.bot.x / edge2.dx)
                ip.y = self.round(ip.x / edge2.dx + b2)
        elif edge2.delta.x == 0:
            ip.x = edge2.bot.x
            if self.is_horizontal(edge1):
                ip.y = edge1.bot.y
            else:
                b1 = edge1.bot.y - (edge1.bot.x / edge1.dx)
                ip.y = self.round(ip.x / edge1.dx + b1)
        else:
            b1 = edge1.bot.x - edge1.bot.y * edge1.dx
            b2 = edge2.bot.x - edge2.bot.y * edge2.dx
            q = (b2 - b1) / (edge1.dx - edge2.dx)
            ip.y = self.round(q)
            if abs(edge1.dx) < abs(edge2.dx):
                ip.x = self.round(edge1.dx * q + b1)
            else:
                ip.x = self.round(edge2.dx * q + b2)
        if ip.y < edge1.top.y or ip.y < edge2.top.y:
            if edge1.top.y > edge2.top.y:
                ip.y = edge1.top.y
                ip.x = self.top_x(edge2, edge1.top.y)
                return ip.x < edge1.top.x
            ip.y = edge2.top.y
            ip.x = self.top_x(edge1, edge2.top.y)
            return ip.x > edge2.top.x
        return True

    def dispose_intersect_nodes(self) -> None:
        while self.intersect_nodes is not None:
            i_node = self.intersect_nodes.next
            self.intersect_nodes = i_node

    def process_edges_at_top_of_scanbeam(self, top_y: int) -> None:
        e = self.active_edges
        while e is not None:
            is_maxima_edge = self.is_maxima(e, top_y)
            if is_maxima_edge:
                e_max_pair = self.get_maxima_pair(e)
                is_maxima_edge = e_max_pair is None or not self.is_horizontal(e_max_pair)
            if is_maxima_edge:
                e_prev = e.prev_in_ael
                self.do_maxima(e)
                e = self.active_edges if e_prev is None else e_prev.next_in_ael
            else:
                if self.is_intermediate(e, top_y) and self.is_horizontal(e.next_in_lml):
                    e = self.update_edge_into_ael(e)
                    if e.out_idx >= 0:
                        self.add_out_pt(e, e.bot)
                    self.add_edge_to_sel(e)
                else:
                    e.curr.x = self.top_x(e, top_y)
                    e.curr.y = top_y
                if self.strictly_simple:
                    e_prev = e.prev_in_ael
                    if e.out_idx >= 0 and e.wind_delta != 0 and e_prev is not None and e_prev.out_idx >= 0 and e_prev.curr.x == e.curr.x and e_prev.wind_delta != 0:
                        op = self.add_out_pt(e_prev, e.curr)
                        op2 = self.add_out_pt(e, e.curr)
                        self.add_join(op, op2, e.curr)
                e = e.next_in_ael
        self.process_horizontals(True)
        e = self.active_edges
        while e is not None:
            if self.is_intermediate(e, top_y):
                op = self.add_out_pt(e, e.top) if e.out_idx >= 0 else None
                e = self.update_edge_into_ael(e)
                e_prev = e.prev_in_ael
                e_next = e.next_in_ael
                if e_prev is not None and e_prev.curr.x == e.bot.x and e_prev.curr.y == e.bot.y and op is not None and e_prev.out_idx >= 0 and e_prev.curr.y > e_prev.top.y and self.slopes_equal(e, e_prev) and e.wind_delta != 0 and e_prev.wind_delta != 0:
                    op2 = self.add_out_pt(e_prev, e.bot)
                    self.add_join(op, op2, e.top)
                elif e_next is not None and e_next.curr.x == e.bot.x and e_next.curr.y == e.bot.y and op is not None and e_next.out_idx >= 0 and e_next.curr.y > e_next.top.y and self.slopes_equal(e, e_next) and e.wind_delta != 0 and e_next.wind_delta != 0:
                    op2 = self.add_out_pt(e_next, e.bot)
                    self.add_join(op, op2, e.top)
            e = e.next_in_ael

    def do_maxima(self, e: TEdge) -> None:
        e_max_pair = self.get_maxima_pair(e)
        if e_max_pair is None:
            if e.out_idx >= 0:
                self.add_out_pt(e, e.top)
            self.delete_from_ael(e)
            return
        e_next = e.next_in_ael
        while e_next is not None and e_next != e_max_pair:
            self.intersect_edges(e, e_next, e.top, True)
            self.swap_positions_in_ael(e, e_next)
            e_next = e.next_in_ael
        if e.out_idx == self.unassigned and e_max_pair.out_idx == self.unassigned:
            self.delete_from_ael(e)
            self.delete_from_ael(e_max_pair)
        elif e.out_idx >= 0 and e_max_pair.out_idx >= 0:
            self.intersect_edges(e, e_max_pair, e.top)
        else:
            raise ClipperException("DoMaxima error")

    @staticmethod
    def reverse_paths(polys: List[List[IntPoint]]) -> None:
        for poly in polys:
            poly.reverse()

    @staticmethod
    def orientation(poly: List[IntPoint]) -> bool:
        return Clipper.area(poly) >= 0

    def point_count(self, pts: Optional[OutPt]) -> int:
        if pts is None:
            return 0
        result = 0
        p = pts
        while True:
            result += 1
            p = p.next
            if p == pts:
                break
        return result

    def build_result(self, polyg: List[List[IntPoint]]) -> None:
        polyg.clear()
        for out_rec in self.poly_outs:
            if out_rec is None or out_rec.pts is None:
                continue
            cnt = self.point_count(out_rec.pts)
            if cnt < 2:
                continue
            pg: List[IntPoint] = []
            p = out_rec.pts
            for _ in range(cnt):
                pg.append(p.pt)
                p = p.prev
            polyg.append(pg)

    def fixup_out_polygon(self, out_rec: OutRec) -> None:
        last_ok = None
        out_rec.bottom_pt = None
        pp = out_rec.pts
        while True:
            if pp.prev == pp or pp.prev == pp.next:
                self.dispose_out_pts(pp)
                out_rec.pts = None
                return
            if pp.pt == pp.next.pt or pp.pt == pp.prev.pt or (
                self.slopes_equal_pts(pp.prev.pt, pp.pt, pp.next.pt)
                and (not self.preserve_collinear or not self.pt2_is_between_pt1_and_pt3(pp.prev.pt, pp.pt, pp.next.pt))
            ):
                last_ok = None
                tmp = pp
                pp.prev.next = pp.next
                pp.next.prev = pp.prev
                pp = pp.prev
                tmp = None
            elif pp == last_ok:
                break
            else:
                if last_ok is None:
                    last_ok = pp
                pp = pp.next
        out_rec.pts = pp

    def dup_out_pt(self, out_pt: OutPt, insert_after: bool) -> OutPt:
        result = OutPt()
        result.pt = out_pt.pt
        result.idx = out_pt.idx
        if insert_after:
            result.next = out_pt.next
            result.prev = out_pt
            out_pt.next.prev = result
            out_pt.next = result
        else:
            result.prev = out_pt.prev
            result.next = out_pt
            out_pt.prev.next = result
            out_pt.prev = result
        return result

    def get_overlap(self, a1: int, a2: int, b1: int, b2: int) -> Optional[tuple[int, int]]:
        if a1 < a2:
            if b1 < b2:
                left = max(a1, b1)
                right = min(a2, b2)
            else:
                left = max(a1, b2)
                right = min(a2, b1)
        else:
            if b1 < b2:
                left = max(a2, b1)
                right = min(a1, b2)
            else:
                left = max(a2, b2)
                right = min(a1, b1)
        if left < right:
            return left, right
        return None

    def join_horz(self, op1: OutPt, op1b: OutPt, op2: OutPt, op2b: OutPt, pt: IntPoint, discard_left: bool) -> bool:
        dir1 = Direction.dRightToLeft if op1.pt.x > op1b.pt.x else Direction.dLeftToRight
        dir2 = Direction.dRightToLeft if op2.pt.x > op2b.pt.x else Direction.dLeftToRight
        if dir1 == dir2:
            return False
        if dir1 == Direction.dLeftToRight:
            while op1.next.pt.x <= pt.x and op1.next.pt.x >= op1.pt.x and op1.next.pt.y == pt.y:
                op1 = op1.next
            if discard_left and op1.pt.x != pt.x:
                op1 = op1.next
            op1b = self.dup_out_pt(op1, not discard_left)
            if op1b.pt != pt:
                op1 = op1b
                op1.pt = pt
                op1b = self.dup_out_pt(op1, not discard_left)
        else:
            while op1.next.pt.x >= pt.x and op1.next.pt.x <= op1.pt.x and op1.next.pt.y == pt.y:
                op1 = op1.next
            if not discard_left and op1.pt.x != pt.x:
                op1 = op1.next
            op1b = self.dup_out_pt(op1, discard_left)
            if op1b.pt != pt:
                op1 = op1b
                op1.pt = pt
                op1b = self.dup_out_pt(op1, discard_left)
        if dir2 == Direction.dLeftToRight:
            while op2.next.pt.x <= pt.x and op2.next.pt.x >= op2.pt.x and op2.next.pt.y == pt.y:
                op2 = op2.next
            if discard_left and op2.pt.x != pt.x:
                op2 = op2.next
            op2b = self.dup_out_pt(op2, not discard_left)
            if op2b.pt != pt:
                op2 = op2b
                op2.pt = pt
                op2b = self.dup_out_pt(op2, not discard_left)
        else:
            while op2.next.pt.x >= pt.x and op2.next.pt.x <= op2.pt.x and op2.next.pt.y == pt.y:
                op2 = op2.next
            if not discard_left and op2.pt.x != pt.x:
                op2 = op2.next
            op2b = self.dup_out_pt(op2, discard_left)
            if op2b.pt != pt:
                op2 = op2b
                op2.pt = pt
                op2b = self.dup_out_pt(op2, discard_left)
        if (dir1 == Direction.dLeftToRight) == discard_left:
            op1.prev = op2
            op2.next = op1
            op1b.next = op2b
            op2b.prev = op1b
        else:
            op1.next = op2
            op2.prev = op1
            op1b.prev = op2b
            op2b.next = op1b
        return True

    def join_points(self, j: Join) -> Optional[tuple[OutPt, OutPt]]:
        out_rec1 = self.get_out_rec(j.out_pt1.idx)
        out_rec2 = self.get_out_rec(j.out_pt2.idx)
        op1 = j.out_pt1
        op1b = None
        op2 = j.out_pt2
        op2b = None
        is_horizontal = j.out_pt1.pt.y == j.off_pt.y
        if is_horizontal and j.off_pt == j.out_pt1.pt and j.off_pt == j.out_pt2.pt:
            op1b = op1.next
            while op1b != op1 and op1b.pt == j.off_pt:
                op1b = op1b.next
            reverse1 = op1b.pt.y > j.off_pt.y
            op2b = op2.next
            while op2b != op2 and op2b.pt == j.off_pt:
                op2b = op2b.next
            reverse2 = op2b.pt.y > j.off_pt.y
            if reverse1 == reverse2:
                return None
            if reverse1:
                op1b = self.dup_out_pt(op1, False)
                op2b = self.dup_out_pt(op2, True)
                op1.prev = op2
                op2.next = op1
                op1b.next = op2b
                op2b.prev = op1b
                return op1, op1b
            op1b = self.dup_out_pt(op1, True)
            op2b = self.dup_out_pt(op2, False)
            op1.next = op2
            op2.prev = op1
            op1b.prev = op2b
            op2b.next = op1b
            return op1, op1b
        if is_horizontal:
            op1b = op1
            while op1.prev.pt.y == op1.pt.y and op1.prev != op1b and op1.prev != op2:
                op1 = op1.prev
            while op1b.next.pt.y == op1b.pt.y and op1b.next != op1 and op1b.next != op2:
                op1b = op1b.next
            if op1b.next == op1 or op1b.next == op2:
                return None
            op2b = op2
            while op2.prev.pt.y == op2.pt.y and op2.prev != op2b and op2.prev != op1b:
                op2 = op2.prev
            while op2b.next.pt.y == op2b.pt.y and op2b.next != op2 and op2b.next != op1:
                op2b = op2b.next
            if op2b.next == op2 or op2b.next == op1:
                return None
            overlap = self.get_overlap(op1.pt.x, op1b.pt.x, op2.pt.x, op2b.pt.x)
            if overlap is None:
                return None
            left, right = overlap
            if left <= op1.pt.x <= right:
                pt = op1.pt
                discard_left = op1.pt.x > op1b.pt.x
            elif left <= op2.pt.x <= right:
                pt = op2.pt
                discard_left = op2.pt.x > op2b.pt.x
            elif left <= op1b.pt.x <= right:
                pt = op1b.pt
                discard_left = op1b.pt.x > op1.pt.x
            else:
                pt = op2b.pt
                discard_left = op2b.pt.x > op2.pt.x
            if not self.join_horz(op1, op1b, op2, op2b, pt, discard_left):
                return None
            return op1, op2
        op1b = op1.next
        while op1b.pt == op1.pt and op1b != op1:
            op1b = op1b.next
        reverse1 = op1b.pt.y > op1.pt.y or not self.slopes_equal_pts4(op1.pt, op1b.pt, j.off_pt, j.off_pt)
        if reverse1:
            op1b = op1.prev
            while op1b.pt == op1.pt and op1b != op1:
                op1b = op1b.prev
            if op1b.pt.y > op1.pt.y or not self.slopes_equal_pts4(op1.pt, op1b.pt, j.off_pt, j.off_pt):
                return None
        op2b = op2.next
        while op2b.pt == op2.pt and op2b != op2:
            op2b = op2b.next
        reverse2 = op2b.pt.y > op2.pt.y or not self.slopes_equal_pts4(op2.pt, op2b.pt, j.off_pt, j.off_pt)
        if reverse2:
            op2b = op2.prev
            while op2b.pt == op2.pt and op2b != op2:
                op2b = op2b.prev
            if op2b.pt.y > op2.pt.y or not self.slopes_equal_pts4(op2.pt, op2b.pt, j.off_pt, j.off_pt):
                return None
        if op1b == op1 or op2b == op2 or op1b == op2b or (out_rec1 == out_rec2 and reverse1 == reverse2):
            return None
        if reverse1:
            op1b = self.dup_out_pt(op1, False)
            op2b = self.dup_out_pt(op2, True)
            op1.prev = op2
            op2.next = op1
            op1b.next = op2b
            op2b.prev = op1b
            return op1, op1b
        op1b = self.dup_out_pt(op1, True)
        op2b = self.dup_out_pt(op2, False)
        op1.next = op2
        op2.prev = op1
        op1b.prev = op2b
        op2b.next = op1b
        return op1, op1b

    def poly2_contains_poly1(self, out_pt1: OutPt, out_pt2: OutPt) -> bool:
        pt = out_pt1
        if self.point_on_polygon(pt.pt, out_pt2):
            pt = pt.next
            while pt != out_pt1 and self.point_on_polygon(pt.pt, out_pt2):
                pt = pt.next
            if pt == out_pt1:
                return True
        return self.point_in_polygon(pt.pt, out_pt2)

    def fixup_first_lefts1(self, old_out_rec: OutRec, new_out_rec: OutRec) -> None:
        for out_rec in self.poly_outs:
            if out_rec.pts is not None and out_rec.first_left == old_out_rec:
                if self.poly2_contains_poly1(out_rec.pts, new_out_rec.pts):
                    out_rec.first_left = new_out_rec

    def fixup_first_lefts2(self, old_out_rec: OutRec, new_out_rec: OutRec) -> None:
        for out_rec in self.poly_outs:
            if out_rec.first_left == old_out_rec:
                out_rec.first_left = new_out_rec

    def join_common_edges(self) -> None:
        for j in self.joins:
            out_rec1 = self.get_out_rec(j.out_pt1.idx)
            out_rec2 = self.get_out_rec(j.out_pt2.idx)
            if out_rec1.pts is None or out_rec2.pts is None:
                continue
            if out_rec1 == out_rec2:
                hole_state_rec = out_rec1
            elif self.param1_right_of_param2(out_rec1, out_rec2):
                hole_state_rec = out_rec2
            elif self.param1_right_of_param2(out_rec2, out_rec1):
                hole_state_rec = out_rec1
            else:
                hole_state_rec = self.get_lowermost_rec(out_rec1, out_rec2)
            joined = self.join_points(j)
            if joined is None:
                continue
            p1, p2 = joined
            if out_rec1 == out_rec2:
                out_rec1.pts = p1
                out_rec1.bottom_pt = None
                out_rec2 = self.create_out_rec()
                out_rec2.pts = p2
                self.update_out_pt_idxs(out_rec2)
                if self.poly2_contains_poly1(out_rec2.pts, out_rec1.pts):
                    out_rec2.is_hole = not out_rec1.is_hole
                    out_rec2.first_left = out_rec1
                    if self.using_polytree:
                        self.fixup_first_lefts2(out_rec2, out_rec1)
                    if (out_rec2.is_hole ^ self.reverse_solution) == (self.area_outrec(out_rec2) > 0):
                        self.reverse_poly_pt_links(out_rec2.pts)
                elif self.poly2_contains_poly1(out_rec1.pts, out_rec2.pts):
                    out_rec2.is_hole = out_rec1.is_hole
                    out_rec1.is_hole = not out_rec2.is_hole
                    out_rec2.first_left = out_rec1.first_left
                    out_rec1.first_left = out_rec2
                    if self.using_polytree:
                        self.fixup_first_lefts2(out_rec1, out_rec2)
                    if (out_rec1.is_hole ^ self.reverse_solution) == (self.area_outrec(out_rec1) > 0):
                        self.reverse_poly_pt_links(out_rec1.pts)
                else:
                    out_rec2.is_hole = out_rec1.is_hole
                    out_rec2.first_left = out_rec1.first_left
                    if self.using_polytree:
                        self.fixup_first_lefts1(out_rec1, out_rec2)
            else:
                out_rec2.pts = None
                out_rec2.bottom_pt = None
                out_rec2.idx = out_rec1.idx
                out_rec1.is_hole = hole_state_rec.is_hole
                if hole_state_rec == out_rec2:
                    out_rec1.first_left = out_rec2.first_left
                out_rec2.first_left = out_rec1
                if self.using_polytree:
                    self.fixup_first_lefts2(out_rec2, out_rec1)

    def update_out_pt_idxs(self, out_rec: OutRec) -> None:
        op = out_rec.pts
        while True:
            op.idx = out_rec.idx
            op = op.prev
            if op == out_rec.pts:
                break

    def do_simple_polygons(self) -> None:
        i = 0
        while i < len(self.poly_outs):
            out_rec = self.poly_outs[i]
            i += 1
            op = out_rec.pts
            if op is None:
                continue
            op_start = op
            while True:
                op2 = op.next
                while op2 != out_rec.pts:
                    if op.pt == op2.pt and op2.next != op and op2.prev != op:
                        op3 = op.prev
                        op4 = op2.prev
                        op.prev = op4
                        op4.next = op
                        op2.prev = op3
                        op3.next = op2
                        out_rec.pts = op
                        out_rec2 = self.create_out_rec()
                        out_rec2.pts = op2
                        self.update_out_pt_idxs(out_rec2)
                        if self.poly2_contains_poly1(out_rec2.pts, out_rec.pts):
                            out_rec2.is_hole = not out_rec.is_hole
                            out_rec2.first_left = out_rec
                        elif self.poly2_contains_poly1(out_rec.pts, out_rec2.pts):
                            out_rec2.is_hole = out_rec.is_hole
                            out_rec.is_hole = not out_rec2.is_hole
                            out_rec2.first_left = out_rec.first_left
                            out_rec.first_left = out_rec2
                        else:
                            out_rec2.is_hole = out_rec.is_hole
                            out_rec2.first_left = out_rec.first_left
                        op2 = op
                    op2 = op2.next
                op = op.next
                if op == out_rec.pts:
                    break

    @staticmethod
    def area(poly: List[IntPoint]) -> float:
        high = len(poly) - 1
        if high < 2:
            return 0.0
        area = (poly[high].x + poly[0].x) * (poly[0].y - poly[high].y)
        for i in range(1, high + 1):
            area += (poly[i - 1].x + poly[i].x) * (poly[i].y - poly[i - 1].y)
        return area / 2.0

    def area_outrec(self, out_rec: OutRec) -> float:
        op = out_rec.pts
        if op is None:
            return 0.0
        a = 0.0
        while True:
            a += (op.pt.x + op.prev.pt.x) * (op.prev.pt.y - op.pt.y)
            op = op.next
            if op == out_rec.pts:
                break
        return a / 2.0


# OffsetPolygon functions

def get_unit_normal(pt1: IntPoint, pt2: IntPoint) -> DoublePoint:
    dx = pt2.x - pt1.x
    dy = pt2.y - pt1.y
    if dx == 0 and dy == 0:
        return DoublePoint()
    f = 1.0 / math.sqrt(dx * dx + dy * dy)
    dx *= f
    dy *= f
    return DoublePoint(dy, -dx)


class PolyOffsetBuilder:
    def __init__(
        self,
        pts: List[List[IntPoint]],
        delta: float,
        jointype: int,
        endtype: int,
        limit: float = 0.0,
    ) -> None:
        self.p = pts
        self.current_poly: List[IntPoint] = []
        self.normals: List[DoublePoint] = []
        self.delta = delta
        self.sin_a = 0.0
        self.sin = 0.0
        self.cos = 0.0
        self.steps360 = 0.0
        self.jointype = jointype
        self.endtype = endtype
        self.solution: List[List[IntPoint]] = []
        if ClipperBase.near_zero(delta):
            self.solution = pts
            return
        if endtype != EndType.etClosed and delta < 0:
            delta = -delta
            self.delta = delta
        if jointype == JoinType.jtMiter:
            if limit > 2:
                self.miter_lim = 2 / (limit * limit)
            else:
                self.miter_lim = 0.5
            if endtype == EndType.etRound:
                limit = 0.25
        else:
            self.miter_lim = 0.0
        if jointype == JoinType.jtRound or endtype == EndType.etRound:
            if limit <= 0:
                limit = 0.25
            elif limit > abs(delta) * 0.25:
                limit = abs(delta) * 0.25
            self.steps360 = math.pi / math.acos(1 - limit / abs(delta))
            self.sin = math.sin(2 * math.pi / self.steps360)
            self.cos = math.cos(2 * math.pi / self.steps360)
            self.steps360 /= math.pi * 2
            if delta < 0:
                self.sin = -self.sin
        self.build()

    def add_point(self, pt: IntPoint) -> None:
        self.current_poly.append(pt)

    def do_square(self, k: int, j: int, m: int) -> None:
        dx = math.tan(math.atan2(self.sin_a, self.normals[k].x * self.normals[j].x + self.normals[k].y * self.normals[j].y) / 4)
        p = self.p[m][j]
        self.add_point(IntPoint(round_int(p.x + self.delta * (self.normals[k].x - self.normals[k].y * dx)), round_int(p.y + self.delta * (self.normals[k].y + self.normals[k].x * dx))))
        self.add_point(IntPoint(round_int(p.x + self.delta * (self.normals[j].x + self.normals[j].y * dx)), round_int(p.y + self.delta * (self.normals[j].y - self.normals[j].x * dx))))

    def do_miter(self, r: float, k: int, j: int, m: int) -> None:
        q = self.delta / r
        p = self.p[m][j]
        self.add_point(IntPoint(round_int(p.x + (self.normals[k].x + self.normals[j].x) * q), round_int(p.y + (self.normals[k].y + self.normals[j].y) * q)))

    def do_round(self, k: int, j: int, m: int) -> None:
        a = math.atan2(self.sin_a, self.normals[k].x * self.normals[j].x + self.normals[k].y * self.normals[j].y)
        steps = int(round_int(self.steps360 * abs(a)))
        x = self.normals[k].x
        y = self.normals[k].y
        p = self.p[m][j]
        for _ in range(steps):
            self.add_point(IntPoint(round_int(p.x + x * self.delta), round_int(p.y + y * self.delta)))
            x2 = x
            x = x * self.cos - self.sin * y
            y = x2 * self.sin + y * self.cos
        self.add_point(IntPoint(round_int(p.x + self.normals[j].x * self.delta), round_int(p.y + self.normals[j].y * self.delta)))

    def offset_point(self, k: int, j: int, m: int) -> int:
        self.sin_a = self.normals[k].x * self.normals[j].y - self.normals[j].x * self.normals[k].y
        if self.sin_a > 1.0:
            self.sin_a = 1.0
        elif self.sin_a < -1.0:
            self.sin_a = -1.0
        p = self.p[m][j]
        if self.sin_a * self.delta < 0:
            self.add_point(IntPoint(round_int(p.x + self.normals[k].x * self.delta), round_int(p.y + self.normals[k].y * self.delta)))
            self.add_point(IntPoint(p.x, p.y))
            self.add_point(IntPoint(round_int(p.x + self.normals[j].x * self.delta), round_int(p.y + self.normals[j].y * self.delta)))
        else:
            if self.jointype == JoinType.jtMiter:
                r = 1 + (self.normals[j].x * self.normals[k].x + self.normals[j].y * self.normals[k].y)
                if r >= self.miter_lim:
                    self.do_miter(r, k, j, m)
                else:
                    self.do_square(k, j, m)
            elif self.jointype == JoinType.jtSquare:
                self.do_square(k, j, m)
            else:
                self.do_round(k, j, m)
        return j

    def build(self) -> None:
        for m, poly in enumerate(self.p):
            length = len(poly)
            if length == 0 or (length < 3 and self.delta <= 0):
                continue
            if length == 1:
                self.current_poly = []
                if self.jointype == JoinType.jtRound:
                    x = 1.0
                    y = 0.0
                    for _ in range(1, round_int(self.steps360 * 2 * math.pi) + 1):
                        self.add_point(IntPoint(round_int(poly[0].x + x * self.delta), round_int(poly[0].y + y * self.delta)))
                        x2 = x
                        x = x * self.cos - self.sin * y
                        y = x2 * self.sin + y * self.cos
                else:
                    x = -1.0
                    y = -1.0
                    for _ in range(4):
                        self.add_point(IntPoint(round_int(poly[0].x + x * self.delta), round_int(poly[0].y + y * self.delta)))
                        if x < 0:
                            x = 1.0
                        elif y < 0:
                            y = 1.0
                        else:
                            x = -1.0
                self.solution.append(self.current_poly)
                continue
            self.normals = []
            for j in range(length - 1):
                self.normals.append(get_unit_normal(poly[j], poly[j + 1]))
            if self.endtype == EndType.etClosed:
                self.normals.append(get_unit_normal(poly[length - 1], poly[0]))
            else:
                self.normals.append(DoublePoint(self.normals[length - 2].x, self.normals[length - 2].y))
            self.current_poly = []
            if self.endtype == EndType.etClosed:
                k = length - 1
                for j in range(length):
                    k = self.offset_point(k, j, m)
                self.solution.append(self.current_poly)
            else:
                k = 0
                for j in range(1, length - 1):
                    k = self.offset_point(k, j, m)
                j = length - 1
                if self.endtype == EndType.etButt:
                    self.add_point(IntPoint(round_int(poly[j].x + self.normals[j].x * self.delta), round_int(poly[j].y + self.normals[j].y * self.delta)))
                    self.add_point(IntPoint(round_int(poly[j].x - self.normals[j].x * self.delta), round_int(poly[j].y - self.normals[j].y * self.delta)))
                else:
                    k = length - 2
                    self.sin_a = 0.0
                    self.normals[j].x = -self.normals[j].x
                    self.normals[j].y = -self.normals[j].y
                    if self.endtype == EndType.etSquare:
                        self.do_square(k, j, m)
                    else:
                        self.do_round(k, j, m)
                for j in range(length - 1, 0, -1):
                    self.normals[j].x = -self.normals[j - 1].x
                    self.normals[j].y = -self.normals[j - 1].y
                self.normals[0].x = -self.normals[1].x
                self.normals[0].y = -self.normals[1].y
                k = length - 1
                for j in range(k - 1, 0, -1):
                    k = self.offset_point(k, j, m)
                if self.endtype == EndType.etButt:
                    self.add_point(IntPoint(round_int(poly[0].x - self.normals[0].x * self.delta), round_int(poly[0].y - self.normals[0].y * self.delta)))
                    self.add_point(IntPoint(round_int(poly[0].x + self.normals[0].x * self.delta), round_int(poly[0].y + self.normals[0].y * self.delta)))
                else:
                    k = 1
                    self.sin_a = 0.0
                    if self.endtype == EndType.etSquare:
                        self.do_square(k, 0, m)
                    else:
                        self.do_round(k, 0, m)
                self.solution.append(self.current_poly)


# Cleaning helpers

def distance_sqrd(pt1: IntPoint, pt2: IntPoint) -> float:
    dx = float(pt1.x - pt2.x)
    dy = float(pt1.y - pt2.y)
    return dx * dx + dy * dy


def closest_point_on_line(pt: IntPoint, line_pt1: IntPoint, line_pt2: IntPoint) -> DoublePoint:
    dx = float(line_pt2.x - line_pt1.x)
    dy = float(line_pt2.y - line_pt1.y)
    if dx == 0 and dy == 0:
        return DoublePoint(line_pt1.x, line_pt1.y)
    q = ((pt.x - line_pt1.x) * dx + (pt.y - line_pt1.y) * dy) / (dx * dx + dy * dy)
    return DoublePoint((1 - q) * line_pt1.x + q * line_pt2.x, (1 - q) * line_pt1.y + q * line_pt2.y)


def slopes_near_collinear(pt1: IntPoint, pt2: IntPoint, pt3: IntPoint, dist_sqrd: float) -> bool:
    if distance_sqrd(pt1, pt2) > distance_sqrd(pt1, pt3):
        return False
    cpol = closest_point_on_line(pt2, pt1, pt3)
    dx = pt2.x - cpol.x
    dy = pt2.y - cpol.y
    return (dx * dx + dy * dy) < dist_sqrd


def points_are_close(pt1: IntPoint, pt2: IntPoint, dist_sqrd: float) -> bool:
    dx = float(pt1.x - pt2.x)
    dy = float(pt1.y - pt2.y)
    return (dx * dx + dy * dy) <= dist_sqrd


def clean_polygon(path: List[IntPoint], distance: float = 1.415) -> List[IntPoint]:
    dist_sqrd = distance * distance
    high = len(path) - 1
    result: List[IntPoint] = []
    while high > 0 and points_are_close(path[high], path[0], dist_sqrd):
        high -= 1
    if high < 2:
        return result
    pt = path[high]
    i = 0
    while True:
        while i < high and points_are_close(pt, path[i], dist_sqrd):
            i += 2
        i2 = i
        while i < high and (points_are_close(path[i], path[i + 1], dist_sqrd) or slopes_near_collinear(pt, path[i], path[i + 1], dist_sqrd)):
            i += 1
        if i >= high:
            break
        if i != i2:
            continue
        pt = path[i]
        result.append(pt)
        i += 1
    if i <= high:
        result.append(path[i])
    if len(result) > 2 and slopes_near_collinear(result[-2], result[-1], result[0], dist_sqrd):
        result.pop()
    if len(result) < 3:
        result = []
    return result


def round_int(value: float) -> int:
    return int(value - 0.5) if value < 0 else int(value + 0.5)


def strip_dups_and_get_bot_pt(in_path: List[IntPoint], closed: bool) -> Optional[tuple[List[IntPoint], IntPoint]]:
    if closed:
        while in_path and in_path[0] == in_path[-1]:
            in_path = in_path[:-1]
    if not in_path:
        return None
    out_path = [in_path[0]]
    bot_pt = in_path[0]
    for pt in in_path[1:]:
        if pt == out_path[-1]:
            continue
        out_path.append(pt)
        if pt.y > bot_pt.y or (pt.y == bot_pt.y and pt.x < bot_pt.x):
            bot_pt = pt
    if len(out_path) < 2 or (closed and len(out_path) == 2):
        return None
    return out_path, bot_pt


def offset_paths(polys: List[List[IntPoint]], delta: float, jointype: int, endtype: int, miter_limit: float) -> List[List[IntPoint]]:
    out_polys: List[List[IntPoint]] = []
    bot_idx = -1
    bot_pt = IntPoint(0, 0)
    for poly in polys:
        stripped = strip_dups_and_get_bot_pt(poly, endtype == EndType.etClosed)
        out_path: List[IntPoint] = []
        if stripped is not None:
            out_path, pt = stripped
            if bot_idx < 0 or pt.y > bot_pt.y or (pt.y == bot_pt.y and pt.x < bot_pt.x):
                bot_pt = pt
                bot_idx = len(out_polys)
        out_polys.append(out_path)
    if endtype == EndType.etClosed and bot_idx >= 0 and not Clipper.orientation(out_polys[bot_idx]):
        Clipper.reverse_paths(out_polys)
    builder = PolyOffsetBuilder(out_polys, delta, jointype, endtype, miter_limit)
    return builder.solution
