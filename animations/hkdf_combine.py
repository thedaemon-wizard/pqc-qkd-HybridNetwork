"""HKDF-SHA3-256 combination of QKD and PQC keys.

Render with:
    manim -ql hkdf_combine.py HKDFCombineScene
"""
from manim import *


class HKDFCombineScene(Scene):
    def construct(self) -> None:
        title = Text("Hybrid Key Derivation (HKDF-SHA3-256)", font_size=30).to_edge(UP)
        self.play(Write(title))

        # Inputs
        qkd = Rectangle(width=3.5, height=0.8, color=GREEN, fill_opacity=0.3).shift(UP * 1.5 + LEFT * 3.5)
        qkd_t = Text("QKD key (BB84)", font_size=20).move_to(qkd.get_center())
        pqc = Rectangle(width=3.5, height=0.8, color=PURPLE, fill_opacity=0.3).shift(UP * 1.5 + RIGHT * 3.5)
        pqc_t = Text("PQC key (Rosenpass)", font_size=20).move_to(pqc.get_center())
        self.play(Create(qkd), Write(qkd_t), Create(pqc), Write(pqc_t))

        # HKDF box
        hk = Rectangle(width=4.5, height=1.1, color=ORANGE, fill_opacity=0.3).shift(DOWN * 0.5)
        hk_t = Text("HKDF + SHA3-256", font_size=22).move_to(hk.get_center())
        self.play(Create(hk), Write(hk_t))

        # Arrows
        a1 = Arrow(qkd.get_bottom(), hk.get_top() + LEFT * 1.2, buff=0.1, color=GREEN)
        a2 = Arrow(pqc.get_bottom(), hk.get_top() + RIGHT * 1.2, buff=0.1, color=PURPLE)
        self.play(GrowArrow(a1), GrowArrow(a2))

        # Output PSK
        psk = Rectangle(width=4.0, height=0.9, color=BLUE, fill_opacity=0.3).shift(DOWN * 2.5)
        psk_t = Text("WireGuard PSK (32 bytes)", font_size=20).move_to(psk.get_center())
        a3 = Arrow(hk.get_bottom(), psk.get_top(), buff=0.05, color=BLUE)
        self.play(GrowArrow(a3), Create(psk), Write(psk_t))

        # Annotations
        ann = Text("Rotated every INTERVAL (default 30s in PoC, 120s in paper)",
                   font_size=18, color=YELLOW).to_edge(DOWN)
        self.play(Write(ann))
        self.wait(3)
