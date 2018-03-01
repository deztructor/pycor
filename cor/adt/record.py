import collections
import functools
import itertools
import types

from .error import *
from .operation import (
    as_basic_type,
    convert,
    ContractInfo,
    _obj_info,
    default_conversion,
)


def _get_input_mapping(values, overrides):
    if not values:
        return overrides

    ensure_has_type(collections.Mapping, values)
    return {**values, **overrides}


class RecordBase(collections.Mapping):
    '''Base class for ADT'''

    __slots__ = tuple()
    _fields = {}

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


class Record(RecordBase):
    __slots__ = tuple()
    _service_fields = ('_initialized',)

    def __init__(self, values=None, **overrides):
        values = _get_input_mapping(values, overrides)

        self._initialized = False
        for name, value in self.gen_fields_from_input(values):
            setattr(self, name, value)
        self._initialized = True

    def __setattr__(self, name, value):
        if name not in self.__slots__:
            raise AttributeError()
        if name != '_initialized' and self._initialized:
            raise AccessError()
        super().__setattr__(name, value)

    def gen_names(self):
        yield from self.gen_record_names()

    def __len__(self):
        return len(self._fields)


class ExtensibleRecord(RecordBase):
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


class Factory:
    '''Wraps record construction

    The purpose of factory is to combine record contracts using operators

    '''

    def __init__(self, record_base, cls_name, **fields):
        fields = {k: default_conversion(v) for k, v in fields.items()}

        slots = itertools.chain(
            fields.keys(),
            record_base._service_fields,
            ['__dict__'] if record_base == ExtensibleRecord else []
        )

        cls_dict = {
            '_fields': types.MappingProxyType(fields),
            '__slots__': tuple(slots),
            '_contract_info': ContractInfo('convert to' + cls_name),
            '_factory': self
        }
        self._record_type = type(cls_name, (record_base,), cls_dict)

    def __call__(self, *args, **kwargs):
        return self._record_type(*args, **kwargs)

    def __or__(self, other):
        return convert(self) | other

    def __and__(self, other):
        return convert(self) & other

    @property
    def record_type(self):
        return self._record_type

    def extend(self, cls_name, **augmenting_fields):
        fields = {
            **self._record_type.get_contract(),
            **augmenting_fields
        }
        return Factory(self._record_type, cls_name, **fields)


_obj_info.register(Factory)
def _obj_info_for_factory(obj):
    return obj.record_type.__name__


class RecordFactory(Factory):
    def __init__(self, cls_name, **fields):
        super().__init__(Record, cls_name, **fields)


class ExtensibleRecordFactory(Factory):
    def __init__(self, cls_name, **fields):
        super().__init__(ExtensibleRecord, cls_name, **fields)


subrecord = RecordFactory
extensible_subrecord = ExtensibleRecordFactory


def record(cls_name, **fields):
    return RecordFactory(cls_name, **fields).record_type


def extensible_record(cls_name, **fields):
    return ExtensibleRecordFactory(cls_name, **fields).record_type



