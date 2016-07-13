from cor import *
import unittest

def validate_str(n, v):
    if not isinstance(v, str):
        raise TypeError('Not str {}'.format(n))


class TestStructure(Structure):
    a = Member()
    x = Member(optional=True)

    b = Member()
    y = Member('foo', optional=True)
    z = ValidableMember(optional=True, validate=validate_str)


class StructureTests(unittest.TestCase):
    def test_Structure(self):
        with self.assertRaises(ValueError):
            obj = TestStructure()

        with self.assertRaises(ValueError):
            obj = TestStructure(a=1, x=3, y=4, z=5)

        obj = TestStructure(a=1, b=2)
        self.assertEqual([obj.a, obj.b, obj.x, obj.y], [1, 2, None, 'foo'])

        obj = TestStructure(a=1, b=2, x='bar')
        self.assertEqual([obj.a, obj.b, obj.x, obj.y], [1, 2, 'bar', 'foo'])

        obj.x = 'foobar'
        self.assertEqual([obj.a, obj.b, obj.x, obj.y], [1, 2, 'foobar', 'foo'])

        self.assertEqual(obj.member_names, {'a', 'b', 'x', 'y', 'z'})
        self.assertEqual(obj.optional_members, {'x', 'y', 'z'})
        self.assertEqual(
            obj.as_dict(),
            {'a': 1, 'b': 2, 'x': 'foobar', 'y': 'foo', 'z': None}
        )
        with self.assertRaises(TypeError):
            obj.z = 1
        obj.z = 'Z'
        self.assertEqual(
            obj.as_dict(),
            {'a': 1, 'b': 2, 'x': 'foobar', 'y': 'foo', 'z': 'Z'}
        )


if __name__ == '__main__':
    unittest.main()
