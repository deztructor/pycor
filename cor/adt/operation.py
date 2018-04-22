import abc
import collections
import enum
import functools
import typing

from . import error


@functools.singledispatch
def as_basic_type(v):
    return v


class ContractInfo:
    '''Information about contract'''

    def __init__(self, info):
        self._get_info = info if callable(info) else lambda: info

    def __str__(self):
        return self.contract

    @property
    def contract(self):
        return self._get_info()


def set_contract_info(target, info):
    target._contract_info = ContractInfo(info)

@functools.singledispatch
def get_contract_info(obj):
    return (
        obj.__name__
        if isinstance(obj, type)
        else getattr(obj, '_contract_info', repr(obj))
    )


get_contract_info.register(enum.EnumMeta)
def get_contract_info_for_enum(obj):
    return '{}({})'.format(obj.__name__, ', '.join('"{}"'.format(v.value) for v in obj))


class Operation(abc.ABC):
    @property
    @abc.abstractmethod
    def info(self) -> str:
        '''get operation contract info'''

    @abc.abstractmethod
    def prepare_field(self, field_name: str, values: collections.Mapping):
        '''extract and convert data for the field

        Function should extract and convert field value from the provided
        `values` mapping or return `None` if target field shouldn't be set.

        '''

    def __str__(self):
        return self.info

    def __repr__(self):
        return '{}({})'.format(self.__class__.__name__, self.info)


class CombineMixin:
    def __rshift__(self, fn):
        return Pipe(self, default_conversion(fn))

    def __or__(self, fn):
        return Or(self, default_conversion(fn))


get_contract_info.register(Operation)
def get_contract_info_for_operation(obj):
    return obj.info


@functools.singledispatch
def default_conversion(obj):
    return SimpleConversion(obj)


@default_conversion.register(type)
def default_conversion_for_type(obj):
    return expect_type(obj)


@default_conversion.register(Operation)
def default_conversion_for_operation(obj):
    return obj


class UnaryOperation(Operation, CombineMixin):
    '''An operation performing conversion using `convert` function

    This is abstract class providing basic policies. Subclass should implement
    `prepare_field()`, deciding on source data extraction policy.

    '''

    def __init__(self, convert):
        super().__init__()
        if isinstance(convert, Operation):
            assert isinstance(convert, UnaryOperation)
            self._convert = convert._convert
        else:
            self._convert = convert

    @property
    def info(self):
        res = get_contract_info(self._convert)
        return str(res) if isinstance(res, ContractInfo) else 'convert to ' + res

    def _convert_field(self, field_name, value):
        try:
            return self._convert(value)
        except error.Error:
            raise
        except Exception as err:
            raise error.InvalidFieldError(field_name, get_contract_info(err)) from err


class SimpleConversion(UnaryOperation):
    '''Operation converting data from the input using `convert`

    If field is missing the operation ends up in the MissingFieldError

    '''

    def convert(self, value):
        return self._convert(value)

    def prepare_field(self, field_name, values):
        try:
            input_data = values[field_name]
        except KeyError as err:
            raise error.MissingFieldError(field_name) from err
        except Exception as err:
            raise error.InvalidFieldError(field_name, get_contract_info(err)) from err

        return self._convert_field(field_name, input_data)


class BinaryOperation(Operation):
    '''Operation combining two operations'''

    def __init__(self, left: Operation, right: Operation):
        self._left = left
        self._right = right

    @property
    def info(self):
        return '{} {} {}'.format(
            get_contract_info(self._left),
            self._operation_name,
            get_contract_info(self._right)
        )



class Pipe(BinaryOperation, CombineMixin):
    _operation_name = 'then'

    def prepare_field(self, field_name, values):
        left_res = self._left.prepare_field(field_name, values)
        return (
            None if left_res is None
            else
            self._right.prepare_field(field_name, {**values, field_name: left_res})
        )


class Or(BinaryOperation, CombineMixin):
    _operation_name = 'or'

    def prepare_field(self, field_name, values):
        try:
            res = self._left.prepare_field(field_name, values)
        except Exception as err_left:
            try:
                return self._right.prepare_field(field_name, values)
            except Exception as err_right:
                raise err_right from err_left
        else:
            return (
                self._right.prepare_field(field_name, values)
                if res is None
                else res
            )


def describe_contract(info):
    def decorator(fn):
        set_contract_info(fn, info)
        return fn
    return decorator


def convert(fn: typing.Union[Operation, typing.Callable]) -> Operation:
    '''treat provided callable as simple conversion'''
    return fn if isinstance(fn, Operation) else SimpleConversion(fn)


class Tag(enum.Enum):
    def __str__(self):
        return str(self.value)


@default_conversion.register(Tag)
def _(obj):
    return should_be(obj)


@as_basic_type.register(Tag)
def tag_as_basic_type(v):
    return v.value


class _SkipMissing(UnaryOperation):
    def __init__(self):
        @describe_contract('skip missing')
        def identity(v):
            return v

        super().__init__(identity)

    def prepare_field(self, field_name, values):
        input_data = values.get(field_name)
        return input_data or self._convert_field(field_name, input_data)

    def __rshift__(self, other):
        return Pipe(self, other)


skip_missing = _SkipMissing()


class _ProvideMissing(SimpleConversion):
    def __init__(self, default_value):
        @describe_contract('provide {} if missing'.format(default_value))
        def replace_optional(v):
            return default_value if v is None else v

        super().__init__(replace_optional)

    def prepare_field(self, field_name, values):
        return self._convert_field(field_name, values.get(field_name))


provide_missing = _ProvideMissing


class _GenerateMissing(SimpleConversion):
    def __init__(self, get_default_value):
        @describe_contract(
            'generate {} if missing'.format(get_contract_info( get_default_value))
        )
        def replace_optional(v):
            return get_default_value() if v is None else v

        super().__init__(replace_optional)

    def prepare_field(self, field_name, values):
        return self._convert_field(field_name, values.get(field_name))


generate_missing = _GenerateMissing


def only_if(fn, info, err_cls=ValueError):
    cond = error.ensure_callable(fn)

    @describe_contract(lambda: 'accept only if ' + ContractInfo(info).contract)
    def convert_only_if(v):
        if not cond(v):
            raise err_cls({
                'info': "Value doesn't match condition",
                'condition': info or repr(fn),
                'value': v
            })
        return v

    return convert(convert_only_if)


def expect_types(*expected_types):
    assert expected_types
    type_names = [t.__name__ for t in expected_types]

    def has_expected_types(v):
        return isinstance(v, expected_types)

    info = (
        'has type {}'.format(type_names[0]) if len(type_names) == 1
        else 'has one of {} types'.format(type_names)
    )
    return only_if(has_expected_types, info, TypeError)


def expect_type(expected_type):
    return expect_types(expected_type)


def should_be(expected):
    def is_value(v):
        return v is expected

    return only_if(is_value, 'value is {} constant'.format(expected))


not_empty = only_if(bool, "not empty")


def choose_by_field(name, union_factories):
    assert(all(isinstance(cls, Factory) for cls in union_factories))

    def _get_choice_info():
        return 'or '.join(get_contract_info(cls) for cls in union_factories)

    def _get_contract_info():
        return ('choose ({}) matching against'
                ' {} field to create one'.format(_get_choice_info(), name)
        )

    @describe_contract(_get_contract_info)
    def create(data):
        matched_cls = None
        for cls in union_factories:
            try:
                cls.prepare_field_from_input(name, data)
                matched_cls = cls
                break
            except Exception as err:
                continue
        if matched_cls is None:
            raise error.InvalidFieldError(
                name,
                "Can't find match for any of ({})".format(_get_choice_info())
            )

        return cls(data)

    return convert(create)
