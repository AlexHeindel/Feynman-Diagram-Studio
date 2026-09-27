import unittest

from feynman_studio.latex_import import import_tikz_feynman
from feynman_studio.latex import latex_source, standalone_source
from feynman_studio.model import Diagram, DiagramError, templates
from feynman_studio.render import display_label


class LatexImportTests(unittest.TestCase):
    def test_common_scattering_graph_is_editable(self):
        source = r"""\feynmandiagram [horizontal=a to b] {
            i1 [particle={$e^-$}] -- [fermion] a -- [photon, edge label={$q$}] b -- [anti fermion] f1,
            i2 -- [fermion] a, b -- [fermion] f2
        };"""
        diagram = import_tikz_feynman(source)
        self.assertEqual((len(diagram.vertices), len(diagram.edges)), (6, 5))
        self.assertEqual(diagram.vertices[0].label, "e^-")
        self.assertEqual(diagram.edges[1].kind, "photon")
        self.assertEqual(diagram.edges[1].label, "q")
        self.assertEqual(diagram.edges[2].arrow, "reverse")
        self.assertLess(diagram.vertices[0].x, diagram.vertices[1].x)
        self.assertEqual(Diagram.from_json(diagram.to_json()), diagram)

    def test_explicit_vertices_and_diagram_star(self):
        source = r"""\begin{feynman}
          \vertex [dot] (a) at (0, 0);
          \vertex (b) at (2, 1) {$\bar{\mu}$};
          \diagram* { (a) -- [fermion, momentum={$p$}, half left] (b) };
        \end{feynman}"""
        diagram = import_tikz_feynman(source)
        self.assertEqual(diagram.vertices[1].label, r"\bar{\mu}")
        self.assertTrue(diagram.vertices[0].visible)
        self.assertLess(diagram.vertices[0].x, diagram.vertices[1].x)
        self.assertGreater(diagram.vertices[0].y, diagram.vertices[1].y)
        self.assertEqual(diagram.edges[0].momentum.label, "p")
        self.assertNotEqual(diagram.edges[0].curvature, 0)

    def test_unsupported_topology_is_rejected(self):
        with self.assertRaises(DiagramError):
            import_tikz_feynman(r"\feynmandiagram { a -- [fermion] {b, c} };")
        with self.assertRaises(DiagramError):
            import_tikz_feynman(r"\begin{tikzpicture}\draw (0,0) -- (1,0);\end{tikzpicture}")

    def test_studio_tikz_export_round_trips_exactly(self):
        diagram = templates()[0]
        for source in (latex_source(diagram, "tikz-feynman"), standalone_source(diagram, "tikz-feynhand")):
            self.assertEqual(import_tikz_feynman(source), diagram)

    def test_overleaf_horizontal_photon_scattering(self):
        source = r"""\feynmandiagram [horizontal=f2 to f3] {
          f1 -- [fermion] f2 -- [fermion] f3 -- [fermion] f4,
          f2 -- [photon] p1,
          f3 -- [photon] p2,
        };"""
        diagram = import_tikz_feynman(source)
        f1, f2, f3, f4, p1, p2 = diagram.vertices
        self.assertLess(f1.x, f2.x)
        self.assertLess(f2.x, f3.x)
        self.assertLess(f3.x, f4.x)
        self.assertEqual((f1.x, f1.y), (p1.x, 80))
        self.assertGreater(p1.y, f2.y)
        self.assertEqual((f4.x, f4.y), (p2.x, 80))
        self.assertGreater(p2.y, f3.y)

    def test_overleaf_styled_s_channel(self):
        source = r"""\feynmandiagram [horizontal=a to b] {
          i1 [particle=\(e^{-}\)] -- [fermion, very thick] a -- [fermion, opacity=0.2] i2 [particle=\(e^{+}\)],
          a -- [red, photon, edge label=\(\gamma\), momentum'={[arrow style=red]\(k\)}] b,
          f1 [particle=\(\mu^{+}\)] -- [fermion, opacity=0.2] b -- [fermion, very thick] f2 [particle=\(\mu^{-}\)],
        };"""
        diagram = import_tikz_feynman(source)
        i1, a, i2, b, f1, f2 = diagram.vertices
        self.assertEqual([item.label for item in diagram.vertices], ["e^{-}", "", "e^{+}", "", r"\mu^{+}", r"\mu^{-}"])
        self.assertEqual(display_label(i1.label), "e⁻")
        self.assertEqual(display_label(f1.label), "μ⁺")
        self.assertEqual(i1.x, i2.x)
        self.assertEqual(f1.x, f2.x)
        self.assertLess(i1.y, a.y)
        self.assertLess(f1.y, b.y)
        self.assertGreater(i2.y, a.y)
        self.assertGreater(f2.y, b.y)
        self.assertLess(a.x, b.x)
        photon = diagram.edges[2]
        self.assertEqual((photon.kind, photon.color, photon.label), ("photon", "#FF0000", r"\gamma"))
        self.assertEqual((photon.momentum.label, photon.momentum.color, photon.momentum.side), ("k", "#FF0000", "right"))
        self.assertEqual(diagram.edges[1].color, "#CCCCCC")

    def test_overleaf_layered_muon_decay(self):
        source = r"""\feynmandiagram [layered layout, horizontal=a to b] {
          a [particle=\(\mu^{-}\)] -- [fermion] b -- [fermion] f1 [particle=\(\nu_{\mu}\)],
          b -- [boson, edge label'=\(W^{-}\)] c,
          c -- [anti fermion] f2 [particle=\(\overline \nu_{e}\)],
          c -- [fermion] f3 [particle=\(e^{-}\)],
        };"""
        diagram = import_tikz_feynman(source)
        a, b, f1, c, f2, f3 = diagram.vertices
        self.assertLess(a.x, b.x)
        self.assertEqual(b.y, a.y)
        self.assertLess(f1.y, b.y)
        self.assertEqual(f1.x, c.x)
        self.assertGreater(c.y, b.y)
        self.assertEqual(f2.x, f3.x)
        self.assertLess(f2.y, c.y)
        self.assertGreater(f3.y, c.y)
        self.assertEqual(display_label(f2.label), "ν̄_e")
        self.assertEqual((diagram.edges[2].kind, diagram.edges[2].label), ("photon", "W^{-}"))
        self.assertEqual(diagram.edges[3].arrow, "reverse")

    def test_overleaf_relative_muon_decay(self):
        source = r"""\begin{tikzpicture}
          \begin{feynman}
            \vertex (a) {\(\mu^{-}\)};
            \vertex [right=of a] (b);
            \vertex [above right=of b] (f1) {\(\nu_{\mu}\)};
            \vertex [below right=of b] (c);
            \vertex [above right=of c] (f2) {\(\overline \nu_{e}\)};
            \vertex [below right=of c] (f3) {\(e^{-}\)};
            \diagram* {
              (a) -- [fermion] (b) -- [fermion] (f1),
              (b) -- [boson, edge label'=\(W^{-}\)] (c),
              (c) -- [anti fermion] (f2),
              (c) -- [fermion] (f3),
            };
          \end{feynman}
        \end{tikzpicture}"""
        diagram = import_tikz_feynman(source)
        a, b, f1, c, f2, f3 = diagram.vertices
        self.assertLess(a.x, b.x)
        self.assertEqual(a.y, b.y)
        self.assertLess(f1.y, b.y)
        self.assertGreater(c.y, b.y)
        self.assertEqual(f1.x, c.x)
        self.assertEqual(f2.y, b.y)
        self.assertGreater(f3.y, c.y)
        self.assertEqual(display_label(f2.label), "ν̄_e")
        self.assertEqual(diagram.edges[2].kind, "photon")
        self.assertEqual(Diagram.from_json(diagram.to_json()), diagram)

    def test_unresolved_relative_vertex_is_rejected(self):
        source = r"\vertex [right=of missing] (a); \diagram* { (a) -- [fermion] (b) };"
        with self.assertRaisesRegex(DiagramError, "unknown or circular"):
            import_tikz_feynman(source)

    def test_overleaf_triangular_loop_and_layout_edge(self):
        source = r"""\feynmandiagram [small, horizontal=a to t1] {
          a [particle=\(\pi^{0}\)] -- [scalar] t1 -- t2 -- t3 -- t1,
          t2 -- [photon] p1 [particle=\(\gamma\)],
          t3 -- [photon] p2 [particle=\(\gamma\)],
          p1 -- [opacity=0.2] p2,
        };"""
        diagram = import_tikz_feynman(source)
        a, t1, t2, t3, p1, p2 = diagram.vertices
        self.assertEqual((len(diagram.vertices), len(diagram.edges)), (6, 7))
        self.assertLess(a.x, t1.x)
        self.assertLess(t1.x, t2.x)
        self.assertEqual(t2.x, t3.x)
        self.assertEqual(p1.x, p2.x)
        self.assertLess(t2.x, p1.x)
        self.assertEqual((p1.y, p2.y), (t2.y, t3.y))
        self.assertLess(p1.y, p2.y)
        self.assertEqual(diagram.edges[-1].color, "#CCCCCC")
        self.assertEqual([diagram.edges[index].kind for index in (0, 4, 5)], ["scalar", "photon", "photon"])
        self.assertEqual(Diagram.from_json(diagram.to_json()), diagram)

        without_constraint = source.replace("          p1 -- [opacity=0.2] p2,\n", "")
        open_diagram = import_tikz_feynman(without_constraint)
        _, open_t1, open_t2, open_t3, open_p1, open_p2 = open_diagram.vertices
        self.assertEqual(len(open_diagram.edges), 6)
        self.assertEqual(open_p1.x, open_p2.x)
        self.assertLess(open_p1.y, open_t2.y)
        self.assertLess(open_t2.y, open_t1.y)
        self.assertLess(open_t1.y, open_t3.y)
        self.assertLess(open_t3.y, open_p2.y)

        invisible = import_tikz_feynman(source.replace("opacity=0.2", "draw=none"))
        self.assertEqual(len(invisible.edges), 6)
        self.assertEqual((invisible.vertices[4].x, invisible.vertices[4].y), (p1.x, p1.y))


if __name__ == "__main__":
    unittest.main()
