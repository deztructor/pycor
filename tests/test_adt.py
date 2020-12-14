from collections import namedtuple
from enum import Enum
from functools import partial
import types

import pytest

from cor.adt.error import (
    AccessError,
    InvalidFieldError,
    MissingFieldError,
    RecordError,
)
from cor.adt.hook import (
    HooksFactory,
    field_invariant,
    Target,
)
from cor.adt.record import (
    as_basic_type,
    ExtensibleRecord,
    Factory,
    Record,
    RecordMixin,
    subrecord,
    record_factory,
)
from cor.adt.operation import (
    anything,
    ContractInfo,
    convert,
    default_conversion,
    expect_type,
    expect_types,
    get_contract_info,
    not_empty,
    only_if,
    provide_missing,
    should_be,
    skip_missing,
    something,
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
        test_info = '{}: Correct input: {}'.format(info, input_data)
        res = convert(*input_data)
        assert res == expected, test_info

    for input_data, err in bad:
        test_info = '{}: Should cause exception: {}'.format(info, input_data)
        with pytest.raises(err):
            convert(*input_data)
            pytest.fail(test_info)


def _test_conversion(conversion, *args, **kwargs):
    good, bad = _prepare_test_args(*args, **kwargs)
    good = [([value], res) for value, res in good]
    bad = [([value], res) for value, res in bad]
    _test_good_bad(conversion.info, conversion.convert, good, bad)


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
    _test_conversion(
        provide_missing('foo'),
        Input.Good, (13, 13), ('', ''), (None, 'foo'),
    )
    _test_conversion(
        provide_missing({'a': 1, 'b': 2}),
        Input.Good, (13, 13), ('', ''), (None, {'a': 1, 'b': 2}),
    )


def test_only_if():
    conversion = only_if(lambda x: x < 10, 'less than 10')

    _test_conversion(
        conversion,
        Input.Good, (9, 9),
        Input.Bad, (10, ValueError)
    )

    _test_prepare_field(
        conversion,
        Input.Good,
        ('foo', {'foo': 9}, 9),
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
        ('foo', {'bar': 1, 'foo': 2}, 2),
    )


def test_something():
    conversion = something
    _test_prepare_field(
        conversion,
        Input.Good,
        ('foo', {'foo': 1}, 1),
        ('foo', {'foo': '1'}, '1'),
        Input.Bad,
        ('foo', None, TypeError),
        ('foo', {}, KeyError),
        ('foo', {'bar': 1}, KeyError),
    )


def test_anything():
    conversion = anything
    _test_prepare_field(
        conversion,
        Input.Good,
        ('foo', {}, None),
        ('foo', {'foo': 1}, 1),
        ('foo', {'foo': '1'}, '1'),
        Input.Bad,
        ('foo', None, AttributeError),
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
        Input.Good, ('foo', {'foo': b'bar'}, b'bar'),
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
        ('foo', {'foo': value}, res)
        for value, res in good
    ]
    bad = [
        ('foo', {'foo': value}, err)
        for value, err in bad
    ]
    _test_prepare_field(conversion, good=good, bad=bad)


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

    conversion = provide_missing(42) | int
    _test_prepare_field(
        conversion,
        Input.Good,
        ('foo', {}, 42),
        ('foo', {'foo': 13}, 13),
    )


def test_and():
    conversion = convert(int) >> convert(str)

    _test_binop_conversion(
        conversion,
        Input.Good,
        ('1', '1'),
        (True, '1'),
        Input.Bad,
        ('s', InvalidFieldError),
        (None, InvalidFieldError),
    )

    conversion = conversion >> convert(float)
    _test_binop_conversion(
        conversion,
        Input.Good,
        ('1', 1.0),
        (1.1, 1.0),
        Input.Bad,
        ('s', InvalidFieldError),
        (None, InvalidFieldError),
    )

    conversion = skip_missing >> convert(int)
    _test_prepare_field(
        conversion,
        Input.Good,
        ('foo', {'foo': '1'}, 1),
        ('foo', {}, None),
        Input.Bad,
        ('foo', {'foo': 's'}, InvalidFieldError),
    )

    conversion = provide_missing(42) >> convert(int)
    _test_prepare_field(
        conversion,
        Input.Good,
        ('foo', {}, 42),
        ('foo', {'foo': 13}, 13),
        Input.Bad,
        ('foo', {'foo': 'bar'}, InvalidFieldError),
    )


def test_empty_record():
    class Foo(Record):
        pass

    foo = Foo()
    assert isinstance(foo, Record)
    assert list(foo.gen_names()) == []
    assert list(foo.gen_fields()) == []
    assert as_basic_type(foo) == {}

    @as_basic_type.register(Foo)
    def _(v):
        return v.__class__.__name__

    assert as_basic_type(foo) == 'Foo'

    pytest.raises(AccessError, setattr, foo, 'bar', 1)
    pytest.raises(AttributeError, getattr, foo, 'bar')

    foo_factory = record_factory('Foo')
    assert isinstance(foo_factory, Factory)

    foo2 = foo_factory()
    assert isinstance(foo2, Record)
    assert list(foo2.gen_fields()) == []
    assert as_basic_type(foo2) == {}


def test_minimal_record():
    class Foo(Record):
        id = expect_type(int)

    pytest.raises(RecordError, Foo)

    foo = Foo(id=12)
    assert list(foo.gen_names()) == ['id',]
    assert list(foo.gen_fields()) == [('id', 12)]
    assert foo.id == 12
    assert foo == {'id': 12}
    assert Foo(id=11) != foo

    with pytest.raises(AccessError):
        foo.id = 13
        pytest.fail("Shouldn't allow to change fields")

    foo2 = Foo.get_factory()(id=12)
    assert as_basic_type(foo2) == {'id': 12}
    assert foo2 == foo

    class LT24(Record):
        id = convert(int) >> only_if(lambda v: v < 24, '< 24')

    assert LT24(id=12) == foo2
    assert LT24(id=13) != foo2

    class Duet(Record):
        id = convert(int)
        name = convert(str)

    assert Duet(id=99, name='foo') == Duet(id=99, name='foo')
    assert Duet(id=99, name=1) == Duet(id='99', name='1')
    assert Duet(id=99, name='foo') != Duet(id=100, name='foo')
    assert Duet(id=99, name='bar') != Duet(id=99, name='foo')
    assert foo2 != Duet(id=12, name='')


class WheelerType(Tag):
    Bicycle = 'bicycle'
    Car = 'car'
    Truck = 'truck'


def test_extensible_record():

    class Wheeler(ExtensibleRecord):
        vehicle_type = convert(WheelerType)
        model = expect_type(str)
        wheels = expect_type(int)

    pytest.raises(RecordError, Wheeler, vehicle_type='table', model='choo', wheels=4)

    car_data = dict(vehicle_type='car', model='choo', wheels=4, doors=5)
    vehicle = Wheeler(car_data)
    assert as_basic_type(vehicle) == car_data

    car_dict = dict(vehicle_type=WheelerType.Car, model='choo', wheels=4, doors=5)
    assert dict(vehicle) == car_dict

    class Car(Record):
        vehicle_type = should_be(WheelerType.Car)
        model = expect_type(str)
        wheels = expect_type(int)
        doors = expect_type(int)

    car = Car(vehicle)
    assert as_basic_type(car) == car_data

    class BicycleBreakType(Tag):
        Disk = 'disk'
        Rim = 'rim'

    class Bicycle(Record):
        vehicle_type = should_be(WheelerType.Bicycle)
        model = expect_type(str)
        wheels = expect_type(int)
        breaks = convert(BicycleBreakType)

    bicycle_data = dict(vehicle_type='bicycle', model='DIY', wheels=2, breaks='disk')
    vehicle2 = Wheeler(bicycle_data)
    assert vehicle2 != vehicle

    pytest.raises(RecordError, Bicycle, vehicle)
    bicycle = Bicycle(vehicle2)
    assert as_basic_type(bicycle) == bicycle_data

    class Truck(Wheeler):
        vehicle_type = should_be(WheelerType.Truck)
        capacity = expect_type(float)

    truck_data = dict(vehicle_type='truck', model='DIY', wheels=8, capacity=20.5, power=400)
    truck_wheeler = Wheeler(truck_data)
    truck = Truck(truck_wheeler)

    assert as_basic_type(truck) == truck_data, \
        "Truck is still extensible, should return all passed data"
    assert isinstance(truck, Wheeler)

    class PowerTruck(Record, Truck):
        power = expect_type(int)

        def get_truck_data(self):
            return (self.capacity, self.power)

    power_truck = PowerTruck({**truck, 'breaks': 'disk'})
    assert as_basic_type(power_truck) == truck_data, \
        "PowerTruck is not extensible, should drop unknown fields"
    assert power_truck.get_truck_data() == (20.5, 400)

    class BicycleOwner(Record):
        name = expect_type(str)
        transport = subrecord(Bicycle)

    bicycle_owner = BicycleOwner(name='bob', transport=bicycle)
    assert as_basic_type(bicycle_owner) == {'name': 'bob', 'transport': bicycle_data}


def test_subrecord():
    import ipaddress

    class Host(Record):
        name = expect_type(str) >> not_empty
        connection = record_factory(
            'Connection',
            ip=convert(ipaddress.ip_address),
            mask=expect_type(int),
            gateway=convert(ipaddress.ip_address)
        )

    @as_basic_type.register(ipaddress.IPv4Address)
    def ipv4_as_basic_type(v):
        return str(v)

    connection_data = dict(ip='1.2.3.4', mask=24, gateway='1.2.3.1')
    host_data = dict(name='foo', connection=connection_data)
    host = Host(host_data)
    assert as_basic_type(host) == host_data
    pytest.raises(
        RecordError,
        Host, dict(name='bar', connection={**connection_data, 'gateway': 's'})
    )

    class Host2(Record):
        hostname = expect_type(str)
        connection = Host.get_field_converter('connection')

    host2 = Host2(hostname='bar', connection=connection_data)


def test_hooks():
    identity = lambda *args: args
    factory = field_invariant(identity)
    invariants = list(factory.gen_hooks('foo'))
    assert len(invariants) == 1

    identity_invariant = invariants[0]
    assert identity_invariant.hook_target == Target.PostInit
    obj = types.SimpleNamespace(foo=5)
    res = identity_invariant(obj)
    assert res == (obj, 'foo', 5)

    merge_name_value = lambda _1, name, value: '{}-{}'.format(name, value)

    factory2 = factory << field_invariant(merge_name_value)

    invariants = list(factory2.gen_hooks('bar'))
    assert len(invariants) == 2
    assert all(i.hook_target == Target.PostInit for i in invariants)
    obj = types.SimpleNamespace(bar=6)
    assert [i(obj) for i in invariants] == [(obj, 'bar', 6), 'bar-6']

    convert_int = convert(int)
    factory_op_int = convert_int << factory
    assert isinstance(factory_op_int, HooksFactory)
    assert factory.operation == None, \
        "Original factory should remain the same"
    assert factory_op_int.operation == convert_int

    convert_str = convert(str)
    factory_op_str = convert_str << factory << factory_op_int
    assert isinstance(factory_op_str, HooksFactory)
    assert factory.operation == None, \
        "Original factory should remain the same"
    assert factory_op_int.operation == convert_int, \
        "Original factory should remain the same"
    assert factory_op_str.operation == convert_str, \
        "Factory should use the leftmost operation"

    with pytest.raises(TypeError):
        factory << convert_int, \
            "HooksFactory should be added (after) on top of operation tree"

    pytest.raises(ValueError, default_conversion, factory)
    with pytest.raises(ValueError):
        convert_str >> factory, "HooksFactory can't be used in conversion pipe"


def test_invariant():
    import ipaddress

    class Host(Record):
        ip = convert(ipaddress.ip_address)
        mask = expect_type(int)

        @property
        def network(self):
            return ipaddress.ip_network("{}/{}".format(self.ip, self.mask), strict=False)

    @as_basic_type.register(ipaddress.IPv4Address)
    def ipv4_as_basic_type(v):
        return str(v)

    h = Host(ip='1.1.1.1', mask=24)
    assert as_basic_type(h) == {'ip': '1.1.1.1', 'mask': 24}

    def check_gateway(host, _, field_value):
        if not field_value in host.network:
            raise ValueError()

    class NetHost(Host):
        gateway = (
            convert(ipaddress.ip_address)
            << field_invariant(check_gateway)
        )

    h = NetHost(ip='1.1.1.1', mask=24, gateway='1.1.1.2')
    assert as_basic_type(h) == {'gateway': '1.1.1.2', 'ip': '1.1.1.1', 'mask': 24}
    pytest.raises(RecordError, NetHost, ip='1.1.1.1', mask=24, gateway='1.2.1.2')


def test_field_aggregate():
    print('TODO')

def test_contract_info():
    data = (
        (convert(int), "convert to int"),
        (convert(str), "convert to str"),
        (convert(WheelerType), 'convert to WheelerType("bicycle", "car", "truck")'),
        (expect_type(int), "accept only if has type int"),
        (not_empty, "accept only if not empty"),
        (provide_missing(42) >> convert(int), "provide 42 if missing then convert to int"),
        (skip_missing >> convert(int), "skip missing then convert to int"),
        (expect_type(int) | expect_type(str), "accept only if has type int or accept only if has type str"),
        (
            convert(int) >> only_if(lambda v: v > 10, 'value > 10'),
            "convert to int then accept only if value > 10"
        ),
    )
    for conversion, expected_info in data:
        assert get_contract_info(conversion) == expected_info


def test_record_mixin():
    class T(RecordMixin):
        a = expect_type(int)
        b = expect_type(str)

    class A(ExtensibleRecord, T):
        pass

    class B(Record, T):
        c = convert(WheelerType)

    assert list(A.gen_record_names()) == ['a', 'b']
    assert list(B.gen_record_names()) == ['a', 'b', 'c']

    a = A(a=1, b='foo', c='car')
    b = B(a)

    pytest.raises(RecordError, B, c='car')
