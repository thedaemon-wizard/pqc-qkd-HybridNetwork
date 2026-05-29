"""Multi-hop QKD network with PQC E2E overlay.

Render with:
    manim -ql multi_hop_network.py MultiHopScene
"""
from manim import *


class MultiHopScene(Scene):
    def construct(self) -> None:
        title = Text("Multi-hop QKD + PQC E2E (paper §III)", font_size=28).to_edge(UP)
        self.play(Write(title))

        a = Circle(radius=0.45, color=GREEN).shift(LEFT * 5)
        c = Circle(radius=0.45, color=YELLOW).shift(ORIGIN)
        b = Circle(radius=0.45, color=GREEN).shift(RIGHT * 5)
        for node, lbl, pos in [(a, "Alice", LEFT * 5), (c, "Charlie\n(trusted)", ORIGIN), (b, "Bob", RIGHT * 5)]:
            text = Text(lbl, font_size=18).move_to(pos + DOWN * 0.95)
            self.play(Create(node), Write(text), run_time=0.6)

        # QKD hops
        hop1 = Line(a.get_right(), c.get_left(), color=BLUE)
        hop2 = Line(c.get_right(), b.get_left(), color=BLUE)
        hop1_l = Text("QKD hop  PSK rot 30s", font_size=14, color=BLUE).next_to(hop1, UP, buff=0.1)
        hop2_l = Text("QKD hop  PSK rot 30s", font_size=14, color=BLUE).next_to(hop2, UP, buff=0.1)
        self.play(Create(hop1), Create(hop2), Write(hop1_l), Write(hop2_l))

        # E2E PQC arc
        e2e = ArcBetweenPoints(a.get_top() + UP * 0.2, b.get_top() + UP * 0.2, angle=-PI/3, color=PURPLE)
        e2e_l = Text("Rosenpass PQC handshake (end-to-end)", font_size=14, color=PURPLE).next_to(e2e, UP, buff=0.1)
        self.play(Create(e2e), Write(e2e_l))

        note = Text("Composability: each layer rotates independently;\ncompromise of one cryptographic domain ≠ catastrophic.",
                    font_size=18, color=YELLOW).to_edge(DOWN)
        self.play(Write(note))
        self.wait(3)
