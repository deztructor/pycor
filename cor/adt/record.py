import abc
import collections
import functools
import itertools
import types

from .error import *
from .operation import (
    _obj_info,
    as_basic_type,
    ContractInfo,
    convert,
    default_conversion,
    Operation,
)


def _get_input_mapping(values, overrides):
    if not values:
        return overrides

    ensure_has_type(collections.Mapping, values)
    return {**values, **overrides}


class RecordMeta(abc.ABCMeta):
    def __init__(cls, name, bases, namespace, **kwds):
        cls._factory = Factory(cls)

    def __new__(cls, name, bases, namespace, **kwds):
        record_base=bases[0]
        if record_base == RecordBase:
            return super().__new__(cls, name, bases, namespace, **kwds)

        def gen_mro_fields(kls):
            if not hasattr(kls, 'mro'):
                return
            for base in reversed(kls.mro()):
                if issubclass(base, RecordBase):
                    yield base._fields.items()

        ns_fields = []
        ns_wo_fields = {}
        for k, v in namespace.items():
            if isinstance(v, Operation):
                ns_fields.append((k, v))
            else:
                ns_wo_fields[k] = v

        all_bases_fields = (items for base in bases for items in gen_mro_fields(base))
        fields = {k: v for k, v in itertools.chain(*all_bases_fields, ns_fields)}

        slots = itertools.chain(
            fields.keys(),
            record_base._service_fields,
            ['__dict__'] if record_base == ExtensibleRecord else []
        )

        cls_dict = {
            '_fields': types.MappingProxyType(fields),
            '__slots__': tuple(slots),
            '_contract_info': ContractInfo('convert to' + name),
            '_factory': None
        }

        return super().__new__(
            cls, name, (record_base,),
            {**ns_wo_fields, **cls_dict},
            **kwds
        )


class RecordBase(collections.Mapping):
    '''Base class for ADT'''

    __slots__ = tuple()
    _fields = {}
    _factory = None

    @classmethod
    def get_factory(cls):
        return cls._factory

    @classmethod
    def gen_fields_from_input(cls, data: collections.Mapping):
        cls_name = cls.__name__

        for name, conversion in cls._fields.items():
            try:
                name_value = conversion.prepare_field(name, data)
                if name_value is not None:
                    yield name_value
            except Error as err:
                raise RecordError(cls_name, err) from err
            except Exception as err:
                raise RecordError(cls_name, InvalidFieldError(name, err)) from err

    @classmethod
    def get_contract(cls) -> collections.Mapping:
        return cls._fields

    @classmethod
    def prepare_field_from_input(cls, name: str, data: collections.Mapping):
        conversion = cls._fields[name]
        return conversion.prepare_field(name, data)

    @classmethod
    def get_contract_info(cls):
        return '\n'.join(
            '{} :: {}'.format(name, conversion.info)
            for name, conversion in cls._fields.items()
        )

    def gen_fields(self):
        for name in self.gen_names():
            v = getattr(self, name, Ellipsis)
            if v is not Ellipsis:
                yield (name, v)

    @classmethod
    def gen_record_names(cls):
        for name in cls.__slots__:
            if name[0] == '_':
                break
            yield name

    def __eq__(self, other):
        if isinstance(other, self.__class__):
            pairs = zip(self.gen_fields(), other.gen_fields())
            return all(a == b for a, b in pairs)

        if isinstance(other, collections.Mapping):
            if set(self.gen_names()) != other.keys():
                return False

            for k, a in self.gen_fields():
                b = other.get(k, Ellipsis)
                if b is Ellipsis or b != a:
                    return False
            return True

        return False

    def __iter__(self):
        return iter(self.gen_names())

    def __getitem__(self, name):
        try:
            return getattr(self, name)
        except AttributeError as err:
            raise KeyError(name) from err


class Factory:
    '''Wraps record construction

    The purpose of factory is to combine record contracts using operators

    '''
    def __init__(self, record_type):
        self._record_type = record_type

    def __call__(self, *args, **kwargs):
        return self._record_type(*args, **kwargs)

    def __or__(self, other):
        return convert(self) | other

    def __and__(self, other):
        return convert(self) & other

    @property
    def record_type(self):
        return self._record_type


class Record(RecordBase, metaclass=RecordMeta):
    __slots__ = tuple()
    _service_fields = ('_initialized',)

    def __init__(self, values=None, **overrides):
        values = _get_input_mapping(values, overrides)

        self._initialized = False
        for name, value in self.gen_fields_from_input(values):
            setattr(self, name, value)
        self._initialized = True

    def __setattr__(self, name, value):
        if name != '_initialized' and name in self.__slots__ and self._initialized:
            raise AccessError(name)
        super().__setattr__(name, value)

    def gen_names(self):
        yield from self.gen_record_names()

    def __len__(self):
        return len(self._fields)


class ExtensibleRecord(RecordBase, metaclass=RecordMeta):
    '''Base class for ADT'''

    __slots__ = tuple()
    _service_fields = ('_initialized',)

    def __init__(self, values=None, **overrides):
        values = _get_input_mapping(values, overrides)

        self._initialized = False
        for name, value in self.gen_fields_from_input(values):
            setattr(self, name, value)

        other_keys = values.keys() - self._fields.keys()
        for k in other_keys:
            setattr(self, k, values[k])

        self._initialized = True

    def __setattr__(self, name, value):
        if name != '_initialized' and self._initialized:
            raise AccessError()
        super().__setattr__(name, value)

    def __len__(self):
        return len(self._fields) + len(self.__dict__)

    def gen_names(self):
        for name in self.__slots__:
            if name[0] == '_':
                break
            yield name
        yield from self.__dict__.keys()


@as_basic_type.register(RecordBase)
def record_as_basic_type(s):
    return {k: as_basic_type(v) for k, v in s.gen_fields()}


_obj_info.register(Factory)
def _obj_info_for_factory(obj):
    return obj.record_type.__name__


def subrecord(cls_name, **fields):
    return RecordMeta(cls_name, (Record,), fields).get_factory()


def extensible_subrecord(cls_name, **fields):
    return RecordMeta(cls_name, (ExtensibleRecord,), fields).get_factory()
