import unittest

from feynman_studio.latex_import import import_tikz_feynman
from feynman_studio.latex import latex_source, standalone_source
from feynman_studio.model import Diagram, DiagramError, templates


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


if __name__ == "__main__":
    unittest.main()
