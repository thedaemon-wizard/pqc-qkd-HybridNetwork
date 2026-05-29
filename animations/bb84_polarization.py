"""BB84 photon polarization scene.

Render with:
    manim -ql bb84_polarization.py BB84PolarizationScene
"""
from manim import *


class BB84PolarizationScene(Scene):
    def construct(self) -> None:
        title = Text("BB84: Photon Polarization & Measurement", font_size=32)
        self.play(Write(title))
        self.play(title.animate.to_edge(UP))

        # Alice
        alice = Circle(radius=0.4, color=BLUE).shift(LEFT * 5)
        alice_lbl = Text("Alice", font_size=20).next_to(alice, DOWN)
        # Bob
        bob = Circle(radius=0.4, color=GREEN).shift(RIGHT * 5)
        bob_lbl = Text("Bob", font_size=20).next_to(bob, DOWN)
        # Channel
        channel = Line(alice.get_right(), bob.get_left(), color=GREY)
        self.play(Create(alice), Write(alice_lbl), Create(bob), Write(bob_lbl), Create(channel))

        bases = ["+", "x", "+", "x"]
        bits  = [0, 1, 1, 0]
        bob_bases = ["+", "+", "x", "x"]

        for ab, bb, bit, bob_b in zip(bases, ["+", "+", "x", "x"], bits, bob_bases):
            # photon as an arrow whose angle encodes (bit, basis)
            angle = {("+", 0): 0, ("+", 1): PI/2, ("x", 0): PI/4, ("x", 1): -PI/4}[(ab, bit)]
            photon = Arrow(start=ORIGIN, end=RIGHT * 0.5, color=YELLOW, buff=0).rotate(angle)
            photon.move_to(alice.get_right() + RIGHT * 0.3)

            label = Text(f"bit={bit}  basis={ab}", font_size=16, color=YELLOW).next_to(photon, UP)
            self.play(FadeIn(photon), FadeIn(label))
            self.play(photon.animate.move_to(bob.get_left() + LEFT * 0.3), run_time=1.2)

            # Bob basis filter
            filt = Square(side_length=0.6, color=PURPLE).move_to(bob.get_left() + LEFT * 0.6)
            self.play(FadeIn(filt))

            match = (ab == bob_b)
            verdict = "KEEP" if match else "DISCARD"
            color = GREEN if match else RED
            result = Text(f"Bob basis={bob_b} -> {verdict}", font_size=18, color=color).to_edge(DOWN)
            self.play(Write(result))
            self.wait(0.4)
            self.play(FadeOut(photon), FadeOut(filt), FadeOut(label), FadeOut(result))

        sift = Text("Public basis disclosure -> keep only matching positions",
                    font_size=22, color=YELLOW).to_edge(DOWN)
        self.play(Write(sift))
        self.wait(2)
