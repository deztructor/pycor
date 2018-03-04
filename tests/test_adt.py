from collections import namedtuple
from enum import Enum
from functools import partial
import unittest

import pytest

from cor.adt.error import (
    AccessError,
    InvalidFieldError,
    MissingFieldError,
    RecordError,
)
from cor.adt.record import (
    as_basic_type,
    extensible_record,
    ExtensibleRecord,
    Factory,
    Record,
    record,
    subrecord,
)
from cor.adt.operation import (
    ContractInfo,
    convert,
    expect_type,
    expect_types,
    only_if,
    provide_missing,
    should_be,
    skip_missing,
    Tag,
)

from cor.util import split_args


class Input(Enum):
    Good = 'good'
    Bad = 'bad'


def _prepare_test_args(*data, good=list(), bad=list()):
    args, kwargs = split_args(Input, *data)
    assert not args
    good = list(good) + kwargs.get('good', [])
    bad = list(bad) + kwargs.get('bad', [])
    return good + kwargs.get('good', []), bad + kwargs.get('bad', []),


def _test_good_bad(info, convert, good, bad):
    for input_data, expected in good:
        test_info = '{}: Right value: {}'.format(info, input_data)
        res = convert(*input_data)
        assert res == expected, test_info

    for input_data, err in bad:
        test_info = '{}: Should cause exception: {}'.format(info, input_data)
        with pytest.raises(err, message=test_info):
            convert(*input_data)


def _test_conversion(conversion, *args, **kwargs):
    good, bad = _prepare_test_args(*args, **kwargs)
    good = [([value], res) for value, res in good]
    bad = [([value], res) for value, res in bad]
    _test_good_bad(conversion.info, conversion.process_value, good, bad)


def _test_prepare_field(conversion, *args, **kwargs):
    good, bad = _prepare_test_args(*args, **kwargs)
    good = [([name, value], res) for name, value, res in good]
    bad = [([name, value], res) for name, value, res in bad]
    _test_good_bad(conversion.info, conversion.prepare_field, good, bad)


def test_convert():
    conversion = convert(int)
    _test_conversion(
        conversion,
        Input.Good, ('1', 1), (2, 2),
        Input.Bad, (None, TypeError), ('s', ValueError),
    )

def test_provide_missing():
    pytest.raises(ValueError, provide_missing)
    pytest.raises(ValueError, provide_missing, 'foo', bar=1)

    _test_conversion(
        provide_missing('foo'),
        Input.Good, (13, 13), ('', ''), (None, 'foo'),
    )
    _test_conversion(
        provide_missing(a=1, b=2),
        Input.Good, (13, 13), ('', ''), (None, {'a': 1, 'b': 2}),
    )


def test_only_if():
    conversion = only_if(lambda x: x < 10, 'foo')

    _test_conversion(
        conversion,
        Input.Good, (9, 9),
        Input.Bad, (10, ValueError)
    )

    _test_prepare_field(
        conversion,
        Input.Good,
        ('foo', {'foo': 9}, ('foo', 9)),
        Input.Bad,
        ('foo', {'foo': 10}, InvalidFieldError),
        ('foo', {'bar': 10}, MissingFieldError),
    )


def test_skip_missing():
    conversion = skip_missing
    _test_prepare_field(
        conversion,
        Input.Good,
        ('foo', {}, None),
        ('foo', {'bar': 1, 'foo': 2}, ('foo', 2)),
    )


def test_expect_types():
    conversion = expect_types(str, float)

    _test_conversion(
        conversion,
        good=(
            (v, v) for v in
            ['', 'foo', 1.1]
        ),
        bad=(
            (v, TypeError) for v in
            [b'', 1, None]
        )
    )

    conversion = expect_type(bytes)
    _test_conversion(conversion, Input.Good, (b'bar', b'bar'))
    _test_prepare_field(
        conversion,
        Input.Good, ('foo', {'foo': b'bar'}, ('foo', b'bar')),
        Input.Bad, ('foo', 1, InvalidFieldError),
    )


def test_should_be():
    v = dict()
    conversion = should_be(v)
    _test_conversion(
        conversion,
        Input.Good, (v, v),
        Input.Bad, (dict(), ValueError),
    )


def _test_binop_conversion(conversion, *args, **kwargs):
    '''binary op provides only prepare_field method'''

    good, bad = _prepare_test_args(*args, **kwargs)
    good = [
        (['foo', {'foo': value}], ('foo', res))
        for value, res in good
    ]
    bad = [
        (['foo', {'foo': value}], err)
        for value, err in bad
    ]
    _test_good_bad(conversion.info, conversion.prepare_field, good, bad)


def test_or():
    conversion = convert(int) | convert(str)

    class NoStr:
        def __str__(self):
            raise OverflowError()

    no_str_conversion = NoStr()

    _test_binop_conversion(
        conversion,
        Input.Good,
        ('1', 1),
        ('1.1', '1.1'),
        ('s', 's'),
        (None, 'None'),
        Input.Bad,
        (no_str_conversion, InvalidFieldError)
    )

    conversion = conversion | only_if(lambda v: isinstance(v, NoStr), 'is NoStr')
    _test_binop_conversion(
        conversion,
        Input.Good,
        ('1', 1),
        ('1.1', '1.1'),
        ('s', 's'),
        (None, 'None'),
        (no_str_conversion, no_str_conversion),
    )

    conversion = skip_missing | convert(int)
    _test_prepare_field(
        conversion,
        Input.Good,
        ('foo', {'foo': '1'}, ('foo', '1')),
        Input.Bad,
        ('foo', {}, MissingFieldError),
    )

    conversion = provide_missing(42) | int
    _test_prepare_field(
        conversion,
        Input.Good,
        ('foo', {}, ('foo', 42)),
        ('foo', {'foo': 13}, ('foo', 13)),
    )


def test_and():
    conversion = convert(int) & convert(str)

    _test_binop_conversion(
        conversion,
        Input.Good,
        ('1', '1'),
        (True, '1'),
        Input.Bad,
        ('s', InvalidFieldError),
        (None, InvalidFieldError),
    )

    conversion = conversion & convert(float)
    _test_binop_conversion(
        conversion,
        Input.Good,
        ('1', 1.0),
        (1.1, 1.0),
        Input.Bad,
        ('s', InvalidFieldError),
        (None, InvalidFieldError),
    )

    conversion = skip_missing & convert(int)
    _test_prepare_field(
        conversion,
        Input.Good,
        ('foo', {'foo': '1'}, ('foo', 1)),
        ('foo', {}, None),
        Input.Bad,
        ('foo', {'foo': 's'}, InvalidFieldError),
    )

    conversion = provide_missing(42) & convert(int)
    _test_prepare_field(
        conversion,
        Input.Good,
        ('foo', {}, ('foo', 42)),
        ('foo', {'foo': 13}, ('foo', 13)),
        Input.Bad,
        ('foo', {'foo': 'bar'}, InvalidFieldError),
    )


def test_empty_record():
    foo_cls = record('Foo')
    assert Record in foo_cls.mro()

    foo = foo_cls()
    assert isinstance(foo, Record)
    assert list(foo.gen_names()) == []
    assert list(foo.gen_fields()) == []
    assert as_basic_type(foo) == {}

    @as_basic_type.register(foo_cls)
    def _(v):
        return v.__class__.__name__

    assert as_basic_type(foo) == 'Foo'

    pytest.raises(AttributeError, setattr, foo, 'bar', 1)
    pytest.raises(AttributeError, getattr, foo, 'bar')

    foo_factory = subrecord('Foo')
    assert isinstance(foo_factory, Factory)

    foo2 = foo_factory()
    assert isinstance(foo2, Record)
    assert list(foo2.gen_fields()) == []
    assert as_basic_type(foo2) == {}


def test_minimal_record():
    Foo = record(
        'Foo',
        id=expect_type(int)
    )

    pytest.raises(RecordError, Foo)

    foo = Foo(id=12)
    assert list(foo.gen_names()) == ['id',]
    assert list(foo.gen_fields()) == [('id', 12)]
    assert foo.id == 12
    assert foo == {'id': 12}
    assert Foo(id=11) != foo

    with pytest.raises(AccessError, msg="Shouldn't allow to change fields"):
        foo.id = 13

    foo2 = Foo.get_factory()(id=12)
    assert as_basic_type(foo2) == {'id': 12}
    assert foo2 == foo

    LT24 = record(
        'LT24',
        id=convert(int) & only_if(lambda v: v < 24, '< 24')
    )

    assert LT24(id=12) == foo2
    assert LT24(id=13) != foo2

    Duet = record(
        'Duet',
        id=convert(int),
        name=convert(str)
    )

    assert Duet(id=99, name='foo') == Duet(id=99, name='foo')
    assert Duet(id=99, name=1) == Duet(id='99', name='1')
    assert Duet(id=99, name='foo') != Duet(id=100, name='foo')
    assert Duet(id=99, name='bar') != Duet(id=99, name='foo')
    assert foo2 != Duet(id=12, name='')


def test_extensible_record():
    class WheelerType(Tag):
        Bicycle = 'bicycle'
        Car = 'car'
        Truck = 'truck'

    Wheeler = extensible_record(
        'Wheeler',
        vehicle_type=convert(WheelerType), model=str, wheels=int
    )

    pytest.raises(RecordError, Wheeler, vehicle_type='table', model='choo', wheels=4)

    car_data = dict(vehicle_type='car', model='choo', wheels=4, doors=5)
    vehicle = Wheeler(car_data)
    assert as_basic_type(vehicle) == car_data

    car_dict = dict(vehicle_type=WheelerType.Car, model='choo', wheels=4, doors=5)
    assert dict(vehicle) == car_dict

    Car = record(
        'Car',
        vehicle_type=WheelerType.Car, model=str, wheels=int,
        doors=int
    )
    car = Car(vehicle)
    assert as_basic_type(car) == car_data

    class BicycleBreakType(Tag):
        Disk = 'disk'
        Rim = 'rim'

    Bicycle = record(
        'Bicycle',
        vehicle_type=WheelerType.Bicycle, model=str, wheels=int,
        breaks=convert(BicycleBreakType)
    )
    bicycle_data = dict(vehicle_type='bicycle', model='DIY', wheels=2, breaks='disk')
    vehicle2 = Wheeler(bicycle_data)
    assert vehicle2 != vehicle

    pytest.raises(RecordError, Bicycle, vehicle)
    bicycle = Bicycle(vehicle2)
    assert as_basic_type(bicycle) == bicycle_data

    Truck = Wheeler.get_factory().extend(
        'Truck',
        vehicle_type=WheelerType.Truck, capacity=float
    )
    truck_data = dict(vehicle_type='truck', model='DIY', wheels=8, capacity=20.5)
    truck_wheeler = Wheeler(truck_data)
    truck = Truck(truck_wheeler)

    assert as_basic_type(truck) == truck_data
    assert isinstance(truck, Wheeler)
