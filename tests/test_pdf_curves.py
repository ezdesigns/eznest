"""Curve flattening must preserve the conservative distance criterion."""
import opt_out
import random
import unittest
from shapely.geometry import LineString, Point
from pdf_io import curve_points


def reference_curve(p0,p1,p2,p3,depth=0,tolerance=.02):
    chord=LineString([p0,p3])
    if depth>=14 or max(chord.distance(Point(p1)),chord.distance(Point(p2)))<=tolerance:
        return [p3]
    def mid(a,b):return [(a[0]+b[0])/2,(a[1]+b[1])/2]
    a,b,c=mid(p0,p1),mid(p1,p2),mid(p2,p3)
    d,e=mid(a,b),mid(b,c);f=mid(d,e)
    return reference_curve(p0,a,d,f,depth+1,tolerance)+reference_curve(f,e,c,p3,depth+1,tolerance)


class PDFCurveTests(unittest.TestCase):
    def test_matches_previous_geometry_across_transforms_and_tolerances(self):
        rng=random.Random(361)
        for scale in (.001,1,1000):
            for _ in range(40):
                points=[[rng.uniform(-200,200)*scale,rng.uniform(-200,200)*scale] for _ in range(4)]
                tolerance=.02*scale
                with self.subTest(scale=scale,points=points):
                    self.assertEqual(curve_points(*points,tolerance=tolerance),reference_curve(*points,tolerance=tolerance))

    def test_endpoint_overshoot_and_closed_loops_are_not_flattened_away(self):
        cases=[([0,0],[100,0],[-100,0],[1,0]),
               ([0,0],[100,100],[-100,100],[0,0]),
               ([10,10],[10,10],[10,10],[10,10])]
        for points in cases:
            with self.subTest(points=points):
                actual=curve_points(*points,tolerance=.01)
                self.assertEqual(actual,reference_curve(*points,tolerance=.01))
                if points[0]!=points[1]:self.assertGreater(len(actual),1)

    def test_dense_curve_samples_remain_within_tolerance_of_flattened_path(self):
        cases=[([0,0],[300,400],[-200,300],[100,0]),
               ([0,0],[1000,.1],[-1000,-.1],[1,0]),
               ([100000,200000],[100100,200400],[99800,200300],[100100,200000])]
        for points in cases:
            tolerance=.02
            line=LineString([points[0]]+curve_points(*points,tolerance=tolerance))
            for i in range(1001):
                t=i/1000;s=1-t
                value=[s**3*points[0][k]+3*s*s*t*points[1][k]+3*s*t*t*points[2][k]+t**3*points[3][k] for k in (0,1)]
                self.assertLessEqual(line.distance(Point(value)),tolerance+1e-8)


if __name__=='__main__':unittest.main()
